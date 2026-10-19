from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.customers.models import Customer
from apps.patients.models import Patient
from apps.pos_shift.models import PosRegister
from apps.pos_transactions.models import PosTransaction
from apps.pos_transactions.refunds import RetailRefundService
from apps.pos_transactions.services import SELLABLE_RETAIL_LOCATION_TYPES, PosRetailService
from apps.prescription.pos_permissions import scope_to_actor_branches
from apps.tenancy.models import Tenant

from .serializers import (
    AddLineRequestSerializer,
    CancelRequestSerializer,
    CashRefundRequestSerializer,
    CashSettlementRequestSerializer,
    CatalogueSearchRequestSerializer,
    CreateDraftRequestSerializer,
    DeviceActionRequestSerializer,
    HoldRequestSerializer,
    PosTransactionLineSerializer,
    PosTransactionSerializer,
    RefundRequestSerializer,
    RefundReviewSerializer,
    RemoveLineRequestSerializer,
    RetailCashRefundSerializer,
    RetailCatalogueItemSerializer,
    RetailRefundRequestSerializer,
    ScanRequestSerializer,
    SetQuantityRequestSerializer,
)


def _tenant(request):
    tenant_id = (
        getattr(request, "tenant_id", None)
        or getattr(getattr(request, "tenant", None), "pk", None)
        or getattr(request.user, "tenant_id", None)
    )
    if tenant_id is None:
        raise DRFValidationError("No tenant context is available.")
    return Tenant.objects.get(pk=tenant_id)


def _run(operation):
    try:
        return operation()
    except PermissionDenied as error:
        raise DRFPermissionDenied(str(error)) from error
    except ValidationError as error:
        raise DRFValidationError(error.messages) from error


def _branch_for_device(*, tenant, device_id):
    registers = list(
        PosRegister.all_objects.filter(tenant=tenant, device_id=device_id).select_related("location")
    )
    if not registers:
        raise DRFValidationError("This device is not assigned to a register.")
    if len(registers) != 1:
        raise DRFValidationError("This device has conflicting register assignments.")
    return registers[0].location


class RetailReadPermission(permissions.BasePermission):
    """Cashiers read their own sales; explicit oversight capabilities read all."""

    oversight = ("pos.transaction.read", "pos.transaction.manage", "pos.shift.manage", "sales.read", "payment.read", "payment.manage", "pos.refund.approve")
    operator = ("pos.transaction.create", "pos.payment.cash.accept", "pos.refund.request", "pos.refund.cash.execute")

    def has_permission(self, request, view):
        if request.method not in permissions.SAFE_METHODS:
            return True  # Domain services enforce action-specific capabilities.
        tenant_id = getattr(request, "tenant_id", None) or getattr(request.user, "tenant_id", None)
        return bool(tenant_id and any(request.user.has_capability(cap, tenant_id=tenant_id) for cap in self.oversight + self.operator))


class PosTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated, RetailReadPermission]
    serializer_class = PosTransactionSerializer

    @action(detail=True, methods=["get", "post"])
    def checkout(self, request, pk=None):
        from apps.prescription.checkout_api import checkout_response
        return checkout_response(request, self.get_object())

    def get_queryset(self):
        tenant_id = (
            getattr(self.request, "tenant_id", None)
            or getattr(getattr(self.request, "tenant", None), "pk", None)
            or getattr(self.request.user, "tenant_id", None)
        )
        if tenant_id is None:
            return PosTransaction.all_objects.none()
        queryset = (
            PosTransaction.all_objects.filter(tenant_id=tenant_id)
            .select_related("branch", "store", "register", "register_session", "operator_shift", "business_day", "operator")
            .prefetch_related("lines__sku__package_definition", "lines__inventory_context", "cash_receipt")
            .order_by("-created_at")
        )
        queryset = scope_to_actor_branches(queryset, self.request)
        if not any(self.request.user.has_capability(cap, tenant_id=tenant_id) for cap in RetailReadPermission.oversight):
            queryset = queryset.filter(operator_id=self.request.user.pk)
            device_id = self.request.headers.get("X-POS-Device-ID") or self.request.query_params.get("device_id")
            if device_id:
                queryset = queryset.filter(device_id=device_id)
        return queryset

    @action(detail=False, methods=["get"], url_path="lookup-receipt")
    def lookup_receipt(self, request):
        number = str(request.query_params.get("receipt_number") or "").strip()
        if not number:
            raise DRFValidationError("Enter the original internal receipt number.")
        record = self.get_queryset().filter(cash_receipt__receipt_number=number).first()
        if not record:
            from rest_framework.exceptions import NotFound
            raise NotFound("Receipt not found within your permitted transactions.")
        return Response(self.get_serializer(record).data)

    @action(detail=False, methods=["post"], url_path="draft")
    def draft(self, request):
        serializer = CreateDraftRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = _tenant(request)
        branch = _branch_for_device(tenant=tenant, device_id=data["device_id"])
        customer = self._customer(tenant, data.get("customer_id"))
        patient = self._patient(tenant, data.get("patient_id"))
        transaction_record = _run(
            lambda: PosRetailService.create_draft(
                tenant=tenant,
                branch=branch,
                store_id=data["store_id"],
                actor=request.user,
                device_id=data["device_id"],
                customer=customer,
                patient=patient,
            )
        )
        return Response(PosTransactionSerializer(transaction_record).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="add-line")
    def add_line(self, request, pk=None):
        serializer = AddLineRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        line = _run(
            lambda: PosRetailService.add_line(
                tenant=_tenant(request), transaction_id=pk, actor=request.user,
                device_id=data["device_id"], sku_id=data["sku_id"], quantity=data["quantity"],
            )
        )
        return Response(PosTransactionLineSerializer(line).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="scan")
    def scan(self, request, pk=None):
        serializer = ScanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = _tenant(request)
        sku = _run(lambda: PosRetailService.resolve_barcode(tenant=tenant, barcode=data["barcode"]))
        from apps.inventory.units import normalize_barcode_quantity
        quantity, evidence = _run(lambda: normalize_barcode_quantity(tenant=tenant, sku=sku, barcode=data["barcode"], quantity=data["quantity"]))
        line = _run(
            lambda: PosRetailService.add_line(
                tenant=tenant, transaction_id=pk, actor=request.user, device_id=data["device_id"],
                sku_id=sku.pk, quantity=quantity, scan_source="BARCODE", unit_evidence=evidence,
            )
        )
        return Response(PosTransactionLineSerializer(line).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="set-quantity")
    def set_quantity(self, request, pk=None):
        serializer = SetQuantityRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        line = _run(
            lambda: PosRetailService.set_quantity(
                tenant=_tenant(request), transaction_id=pk, line_id=data["line_id"], actor=request.user,
                device_id=data["device_id"], quantity=data["quantity"],
            )
        )
        return Response(PosTransactionLineSerializer(line).data)

    @action(detail=True, methods=["post"], url_path="remove-line")
    def remove_line(self, request, pk=None):
        serializer = RemoveLineRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _run(
            lambda: PosRetailService.remove_line(
                tenant=_tenant(request), transaction_id=pk, line_id=data["line_id"], actor=request.user,
                device_id=data["device_id"],
            )
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def hold(self, request, pk=None):
        serializer = HoldRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transaction_record = _run(
            lambda: PosRetailService.hold(
                tenant=_tenant(request), transaction_id=pk, actor=request.user,
                device_id=data["device_id"], reason=data["reason"],
            )
        )
        return Response(PosTransactionSerializer(transaction_record).data)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        serializer = DeviceActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaction_record = _run(
            lambda: PosRetailService.resume(
                tenant=_tenant(request), transaction_id=pk, actor=request.user,
                device_id=serializer.validated_data["device_id"],
            )
        )
        return Response(PosTransactionSerializer(transaction_record).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        serializer = CancelRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transaction_record = _run(
            lambda: PosRetailService.cancel(
                tenant=_tenant(request), transaction_id=pk, actor=request.user,
                device_id=data["device_id"], reason=data["reason"],
            )
        )
        return Response(PosTransactionSerializer(transaction_record).data)

    @action(detail=True, methods=["post"], url_path="ready-for-payment")
    def ready_for_payment(self, request, pk=None):
        serializer = DeviceActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaction_record = _run(
            lambda: PosRetailService.ready_for_payment(
                tenant=_tenant(request), transaction_id=pk, actor=request.user,
                device_id=serializer.validated_data["device_id"],
            )
        )
        return Response(PosTransactionSerializer(transaction_record).data)

    @action(detail=True, methods=["post"], url_path="cash-settle")
    def cash_settle(self, request, pk=None):
        serializer = CashSettlementRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transaction_record = _run(
            lambda: PosRetailService.settle_cash(
                tenant=_tenant(request),
                transaction_id=pk,
                actor=request.user,
                device_id=data["device_id"],
                cash_received=data["cash_received"],
                idempotency_key=data["idempotency_key"],
            )
        )
        return Response(PosTransactionSerializer(transaction_record).data)

    @action(detail=True, methods=["post"], url_path="request-refund")
    def request_refund(self, request, pk=None):
        payload = RefundRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        record = _run(lambda: RetailRefundService.request(tenant=_tenant(request), transaction_id=pk,
            actor=request.user, **payload.validated_data))
        return Response(RetailRefundRequestSerializer(record).data, status=status.HTTP_201_CREATED)

    def _review_refund(self, request, pk, approve):
        payload = RefundReviewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        record = _run(lambda: RetailRefundService.review(tenant=_tenant(request), transaction_id=pk,
            request_id=data["refund_request_id"], actor=request.user, approve=approve, reason=data["reason"]))
        return Response(RetailRefundRequestSerializer(record).data)

    @action(detail=True, methods=["post"], url_path="approve-refund")
    def approve_refund(self, request, pk=None):
        return self._review_refund(request, pk, True)

    @action(detail=True, methods=["post"], url_path="reject-refund")
    def reject_refund(self, request, pk=None):
        return self._review_refund(request, pk, False)

    @action(detail=True, methods=["post"], url_path="cash-refund")
    def cash_refund(self, request, pk=None):
        payload = CashRefundRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        receipt = _run(lambda: RetailRefundService.execute_cash(tenant=_tenant(request), transaction_id=pk,
            request_id=data["refund_request_id"], actor=request.user, device_id=data["device_id"], idempotency_key=data["idempotency_key"], payment_references=data["payment_references"]))
        return Response(RetailCashRefundSerializer(receipt).data)

    @staticmethod
    def _customer(tenant, customer_id):
        if customer_id is None:
            return None
        customer = Customer.all_objects.filter(tenant=tenant, pk=customer_id).first()
        if customer is None:
            raise DRFValidationError("Customer not found in this tenant.")
        return customer

    @staticmethod
    def _patient(tenant, patient_id):
        if patient_id is None:
            return None
        patient = Patient.all_objects.filter(tenant=tenant, pk=patient_id).first()
        if patient is None:
            raise DRFValidationError("Patient not found in this tenant.")
        return patient


class RetailCatalogueViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, RetailReadPermission]

    @action(detail=False, methods=["get"])
    def stores(self, request):
        from apps.inventory.models import InventoryLocation
        tenant = _tenant(request)
        device_id = request.headers.get("X-POS-Device-ID") or request.query_params.get("device_id", "")
        branch = _branch_for_device(tenant=tenant, device_id=device_id)
        rows = scope_to_actor_branches(InventoryLocation.all_objects.filter(
            tenant=tenant, branch=branch, status="ACTIVE",
            location_type__in=SELLABLE_RETAIL_LOCATION_TYPES,
        ), request).values("id", "branch", "name", "location_type", "status", "quarantine_capability")
        return Response(list(rows))

    @action(detail=False, methods=["get"], url_path="return-locations")
    def return_locations(self, request):
        from apps.inventory.models import InventoryLocation
        tenant = _tenant(request)
        device_id = request.headers.get("X-POS-Device-ID") or request.query_params.get("device_id", "")
        branch = _branch_for_device(tenant=tenant, device_id=device_id)
        rows = scope_to_actor_branches(InventoryLocation.all_objects.filter(
            tenant=tenant,
            branch=branch,
            status=InventoryLocation.Status.ACTIVE,
            location_type=InventoryLocation.LocationType.QUARANTINE,
            quarantine_capability=True,
        ), request).values("id", "branch", "name", "location_type", "status", "quarantine_capability")
        return Response(list(rows))

    @action(detail=False, methods=["post"], url_path="search")
    def search(self, request):
        serializer = CatalogueSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = _tenant(request)
        branch = _branch_for_device(tenant=tenant, device_id=data["device_id"])
        customer = PosTransactionViewSet._customer(tenant, data.get("customer_id"))
        items = _run(
            lambda: PosRetailService.search_catalogue(
                tenant=tenant,
                branch=branch,
                store_id=data["store_id"],
                actor=request.user,
                device_id=data["device_id"],
                query=data["query"],
                customer=customer,
            )
        )
        return Response(RetailCatalogueItemSerializer(items, many=True).data)
