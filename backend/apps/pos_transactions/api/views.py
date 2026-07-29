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
from apps.pos_transactions.services import PosRetailService
from apps.tenancy.models import Tenant

from .serializers import (
    AddLineRequestSerializer,
    CancelRequestSerializer,
    CatalogueSearchRequestSerializer,
    CreateDraftRequestSerializer,
    DeviceActionRequestSerializer,
    HoldRequestSerializer,
    PosTransactionLineSerializer,
    PosTransactionSerializer,
    RemoveLineRequestSerializer,
    RetailCatalogueItemSerializer,
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


class PosTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PosTransactionSerializer

    def get_queryset(self):
        tenant_id = (
            getattr(self.request, "tenant_id", None)
            or getattr(getattr(self.request, "tenant", None), "pk", None)
            or getattr(self.request.user, "tenant_id", None)
        )
        if tenant_id is None:
            return PosTransaction.all_objects.none()
        return (
            PosTransaction.all_objects.filter(tenant_id=tenant_id)
            .select_related("branch", "store", "register", "register_session", "operator_shift", "business_day", "operator")
            .prefetch_related("lines__sku__package_definition", "lines__inventory_context")
            .order_by("-created_at")
        )

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
        line = _run(
            lambda: PosRetailService.add_line(
                tenant=tenant, transaction_id=pk, actor=request.user, device_id=data["device_id"],
                sku_id=sku.pk, quantity=data["quantity"], scan_source="BARCODE",
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
    permission_classes = [permissions.IsAuthenticated]

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
