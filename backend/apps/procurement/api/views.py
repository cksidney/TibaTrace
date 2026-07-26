import uuid

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Exists, OuterRef
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.tenant_context import get_current_tenant_id
from apps.inventory.models import InventoryLocation
from apps.inventory.services import InventoryReceiptService
from apps.medicines.models import CommercialSKU
from apps.organizations.models import Location
from apps.procurement.api.serializers import (
    BatchReleaseSerializer,
    GoodsReceiptCreateSerializer,
    GoodsReceiptSerializer,
    PurchaseOrderCreateSerializer,
    PurchaseOrderSerializer,
    PurchaseRequisitionCreateSerializer,
    PurchaseRequisitionSerializer,
    ReceiveBatchSerializer,
    ReceivedBatchSerializer,
    ReceivingInspectionCreateSerializer,
    ReceivingInspectionSerializer,
    SupplierProductAgreementSerializer,
    SupplierQualificationSerializer,
    SupplierReturnCreateSerializer,
    SupplierReturnSerializer,
    SupplierSerializer,
    ThreeWayMatchCreateSerializer,
    ThreeWayMatchSerializer,
)
from apps.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    ReceivedBatch,
    ReceivingInspection,
    Supplier,
    SupplierProductAgreement,
    SupplierQualification,
    SupplierReturn,
    ThreeWayMatch,
)
from apps.procurement.services import (
    BatchReceivingService,
    GoodsReceivingService,
    PurchaseOrderService,
    PurchaseRequisitionService,
    QualityService,
    SupplierGovernanceService,
    SupplierQualificationService,
    SupplierReturnService,
    ThreeWayMatchService,
)
from apps.tenancy.models import Tenant


def _error_payload(exc):
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            return exc.message_dict
        return {"detail": list(getattr(exc, "messages", [str(exc)]))}
    return {"detail": str(exc)}


def _service_error(exc):
    error_status = (
        status.HTTP_403_FORBIDDEN
        if isinstance(exc, DjangoPermissionDenied)
        else status.HTTP_400_BAD_REQUEST
    )
    return Response(_error_payload(exc), status=error_status)


class ProcurementContextView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tenant_id = (
            get_current_tenant_id()
            or getattr(request, "tenant_id", None)
            or getattr(request.user, "tenant_id", None)
        )
        if not tenant_id:
            raise ValidationError({"tenant": "Select a tenant workspace first."})
        return Response(
            {
                "locations": [
                    {
                        "id": str(location.pk),
                        "code": location.code,
                        "name": location.name,
                        "location_type": location.location_type,
                        "status": location.status,
                    }
                    for location in Location.all_objects.filter(
                        tenant_id=tenant_id
                    ).order_by("name")
                ],
                "inventory_locations": [
                    {
                        "id": str(location.pk),
                        "branch": str(location.branch_id),
                        "name": location.name,
                        "location_type": location.location_type,
                        "status": location.status,
                        "quarantine_capability": location.quarantine_capability,
                    }
                    for location in InventoryLocation.all_objects.filter(
                        tenant_id=tenant_id
                    ).order_by("name")
                ],
                "skus": [
                    {
                        "id": str(sku.pk),
                        "sku_code": sku.sku_code,
                        "display_name": sku.display_name,
                        "status": sku.status,
                    }
                    for sku in CommercialSKU.all_objects.filter(
                        tenant_id=tenant_id,
                        is_purchasable=True,
                    ).order_by("display_name", "sku_code")
                ],
            }
        )


class BaseProcurementViewSet(viewsets.ReadOnlyModelViewSet):
    """Read, plus the service-routed actions each subclass declares.

    Read-only deliberately. These were ModelViewSets, which put a generic
    PATCH and DELETE alongside the approve, send and close actions -- writing
    the same columns with none of the checks. A PATCH setting status to APPROVED
    skipped approve_purchase_order and with it the re-check that refuses a
    supplier suspended between drafting and approval; a DELETE removed a
    purchase order outright, when cancellation is a state and deleting the row
    loses what was committed to.

    Every state change goes through an @action that calls a service. Nothing
    reaches these columns any other way.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        tenant_id = get_current_tenant_id() or getattr(self.request, "tenant_id", None)
        if not tenant_id and hasattr(self.request.user, "tenant_id"):
            tenant_id = self.request.user.tenant_id
        if tenant_id:
            # all_objects with an explicit tenant filter, not the default
            # manager. The default is tenant-strict and returns nothing unless
            # tenant context has been set on the thread, which does not happen
            # for an ordinary API request -- so every list came back empty and
            # every detail route 404'd for data that exists.
            return self.model.all_objects.filter(tenant_id=tenant_id)
        return self.model.all_objects.none()

    def perform_create(self, serializer):
        tenant_id = get_current_tenant_id() or getattr(self.request, "tenant_id", None) or getattr(self.request.user, "tenant_id", None)
        serializer.save(tenant_id=tenant_id)

    def current_tenant(self):
        tenant_id = (
            get_current_tenant_id()
            or getattr(self.request, "tenant_id", None)
            or getattr(self.request.user, "tenant_id", None)
        )
        if not tenant_id:
            raise ValidationError({"tenant": "Select a tenant workspace first."})
        try:
            return Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist as exc:
            raise ValidationError({"tenant": "The selected tenant does not exist."}) from exc

    def tenant_object(self, model, object_id, field):
        try:
            return model.all_objects.get(tenant=self.current_tenant(), pk=object_id)
        except model.DoesNotExist as exc:
            raise ValidationError({field: "The selected record is outside this tenant."}) from exc


class SupplierViewSet(BaseProcurementViewSet):
    model = Supplier
    serializer_class = SupplierSerializer

    def get_queryset(self):
        today = timezone.localdate()
        valid_qualifications = SupplierQualification.all_objects.filter(
            supplier_id=OuterRef("pk"),
            verification_status=(
                SupplierQualification.QualificationVerificationStatus.VERIFIED
            ),
            effective_date__lte=today,
            expiry_date__gte=today,
        )
        return super().get_queryset().annotate(
            has_valid_business_registration=Exists(
                valid_qualifications.filter(
                    qualification_type=(
                        SupplierQualification.QualificationType.BUSINESS_REGISTRATION
                    )
                )
            ),
            has_valid_wholesale_dealer_licence=Exists(
                valid_qualifications.filter(
                    qualification_type=(
                        SupplierQualification.QualificationType.WHOLESALE_DEALER_LICENCE
                    )
                )
            ),
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        supplier_code = values.pop("supplier_code")
        legal_name = values.pop("legal_name")
        try:
            supplier = SupplierGovernanceService.create_supplier(
                tenant=self.current_tenant(),
                supplier_code=supplier_code,
                legal_name=legal_name,
                **values,
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(self.get_serializer(supplier).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        supplier = self.get_object()
        try:
            updated = SupplierGovernanceService.approve_supplier(
                supplier=supplier,
                approver=request.user,
                reason=request.data.get("reason", "Approved via API"),
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(SupplierSerializer(updated).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        supplier = self.get_object()
        reason = request.data.get("reason", "Suspended via API")
        try:
            updated = SupplierGovernanceService.suspend_supplier(
                supplier=supplier,
                reason=reason,
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(SupplierSerializer(updated).data, status=status.HTTP_200_OK)


class SupplierQualificationViewSet(BaseProcurementViewSet):
    model = SupplierQualification
    serializer_class = SupplierQualificationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        supplier = serializer.validated_data["supplier"]
        if str(supplier.tenant_id) != str(self.current_tenant().pk):
            raise ValidationError({"supplier": "Supplier is outside this tenant."})
        qualification = serializer.save(tenant=self.current_tenant())
        return Response(self.get_serializer(qualification).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request, pk=None):
        qual = self.get_object()
        try:
            updated = SupplierQualificationService.verify_qualification(
                qualification=qual,
                verifier=request.user,
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(SupplierQualificationSerializer(updated).data, status=status.HTTP_200_OK)


class SupplierProductAgreementViewSet(BaseProcurementViewSet):
    model = SupplierProductAgreement
    serializer_class = SupplierProductAgreementSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.current_tenant()
        supplier = serializer.validated_data["supplier"]
        sku = serializer.validated_data["sku"]
        if str(supplier.tenant_id) != str(tenant.pk) or str(sku.tenant_id) != str(tenant.pk):
            raise ValidationError({"detail": "Supplier and SKU must belong to the selected tenant."})
        agreement = serializer.save(tenant=tenant)
        return Response(self.get_serializer(agreement).data, status=status.HTTP_201_CREATED)


class PurchaseRequisitionViewSet(BaseProcurementViewSet):
    model = PurchaseRequisition
    serializer_class = PurchaseRequisitionSerializer

    def create(self, request, *args, **kwargs):
        serializer = PurchaseRequisitionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.current_tenant()
        branch = self.tenant_object(
            Location,
            serializer.validated_data["requesting_branch"],
            "requesting_branch",
        )
        lines = []
        for item in serializer.validated_data["lines"]:
            lines.append(
                {
                    **item,
                    "sku": self.tenant_object(CommercialSKU, item["sku"], "sku"),
                }
            )
        try:
            requisition = PurchaseRequisitionService.create_requisition(
                tenant=tenant,
                requesting_branch=branch,
                requester=request.user,
                requested_delivery_date=serializer.validated_data["requested_delivery_date"],
                priority=serializer.validated_data["priority"],
                justification=serializer.validated_data["justification"],
                lines_data=lines,
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(
            self.get_serializer(requisition).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        req = self.get_object()
        try:
            updated = PurchaseRequisitionService.submit_requisition(requisition=req)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(
            PurchaseRequisitionSerializer(updated).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        req = self.get_object()
        try:
            updated = PurchaseRequisitionService.approve_requisition(
                requisition=req,
                approver=request.user,
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(PurchaseRequisitionSerializer(updated).data, status=status.HTTP_200_OK)


class PurchaseOrderViewSet(BaseProcurementViewSet):
    model = PurchaseOrder
    serializer_class = PurchaseOrderSerializer

    def create(self, request, *args, **kwargs):
        serializer = PurchaseOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.current_tenant()
        supplier = self.tenant_object(
            Supplier,
            serializer.validated_data["supplier"],
            "supplier",
        )
        branch = self.tenant_object(
            Location,
            serializer.validated_data["ordering_branch"],
            "ordering_branch",
        )
        requisition_id = serializer.validated_data.get("originating_requisition")
        try:
            if requisition_id:
                requisition = self.tenant_object(
                    PurchaseRequisition,
                    requisition_id,
                    "originating_requisition",
                )
                purchase_order = PurchaseOrderService.create_priced_po_from_requisition(
                    tenant=tenant,
                    supplier=supplier,
                    requisition=requisition,
                    ordering_branch=branch,
                    creator=request.user,
                    lines_data=serializer.validated_data["lines"],
                    order_date=serializer.validated_data.get("order_date"),
                    expected_delivery_date=serializer.validated_data["expected_delivery_date"],
                    currency=serializer.validated_data["currency"],
                )
            else:
                lines = [
                    {
                        **item,
                        "sku": self.tenant_object(CommercialSKU, item["sku"], "sku"),
                    }
                    for item in serializer.validated_data["lines"]
                ]
                SupplierGovernanceService.assert_can_receive_purchase_order(
                    supplier=supplier,
                    on_date=serializer.validated_data.get("order_date"),
                    cold_chain=any(item.get("requires_cold_chain") for item in lines),
                )
                purchase_order = PurchaseOrderService.create_purchase_order(
                    tenant=tenant,
                    supplier=supplier,
                    ordering_branch=branch,
                    lines_data=lines,
                    created_by=request.user,
                    order_date=serializer.validated_data.get("order_date"),
                    expected_delivery_date=serializer.validated_data["expected_delivery_date"],
                    currency=serializer.validated_data["currency"],
                )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(self.get_serializer(purchase_order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        po = self.get_object()
        try:
            updated = PurchaseOrderService.approve_po(
                purchase_order=po,
                approver=request.user,
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(PurchaseOrderSerializer(updated).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request, pk=None):
        po = self.get_object()
        try:
            updated = PurchaseOrderService.send_po(purchase_order=po)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(PurchaseOrderSerializer(updated).data, status=status.HTTP_200_OK)


class GoodsReceiptViewSet(BaseProcurementViewSet):
    model = GoodsReceipt
    serializer_class = GoodsReceiptSerializer

    def create(self, request, *args, **kwargs):
        serializer = GoodsReceiptCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.current_tenant()
        purchase_order = self.tenant_object(
            PurchaseOrder,
            serializer.validated_data["purchase_order"],
            "purchase_order",
        )
        branch = self.tenant_object(
            Location,
            serializer.validated_data["receiving_branch"],
            "receiving_branch",
        )
        try:
            receipt = GoodsReceivingService.start_goods_receipt(
                tenant=tenant,
                grn_number=f"GRN-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
                purchase_order=purchase_order,
                receiving_branch=branch,
                receiver=request.user,
                delivery_note_number=serializer.validated_data["delivery_note_number"],
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(self.get_serializer(receipt).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="receive-batch")
    def receive_batch(self, request, pk=None):
        serializer = ReceiveBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receipt = self.get_object()
        po_line = self.tenant_object(
            PurchaseOrderLine,
            serializer.validated_data["po_line"],
            "po_line",
        )
        if po_line.purchase_order_id != receipt.purchase_order_id:
            raise ValidationError({"po_line": "Line does not belong to this purchase order."})
        try:
            batch = GoodsReceivingService.receive_batch(
                goods_receipt=receipt,
                po_line=po_line,
                manufacturer_batch_number=serializer.validated_data[
                    "manufacturer_batch_number"
                ],
                manufacture_date=serializer.validated_data.get("manufacture_date"),
                expiry_date=serializer.validated_data["expiry_date"],
                received_quantity=serializer.validated_data["received_quantity"],
                discrepancy_reason=serializer.validated_data["discrepancy_reason"],
                idempotency_key=serializer.validated_data["idempotency_key"],
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(ReceivedBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def inspect(self, request, pk=None):
        serializer = ReceivingInspectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            inspection = QualityService.record_inspection(
                goods_receipt=self.get_object(),
                inspector=request.user,
                decision=serializer.validated_data["decision"],
                reason=serializer.validated_data["reason"],
                temperature_excursion=serializer.validated_data[
                    "temperature_excursion"
                ],
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(
            ReceivingInspectionSerializer(inspection).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="close")
    def close_receipt(self, request, pk=None):
        grn = self.get_object()
        try:
            updated = GoodsReceivingService.close_goods_receipt(goods_receipt=grn)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(GoodsReceiptSerializer(updated).data, status=status.HTTP_200_OK)


class ReceivedBatchViewSet(BaseProcurementViewSet):
    model = ReceivedBatch
    serializer_class = ReceivedBatchSerializer

    @action(detail=True, methods=["post"], url_path="release")
    def release(self, request, pk=None):
        serializer = BatchReleaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = self.get_object()
        try:
            updated = BatchReceivingService.release_batch(
                batch=batch,
                actor=request.user,
                reason=serializer.validated_data["reason"],
                quantity=serializer.validated_data.get("quantity"),
            )
            inventory_location_id = serializer.validated_data.get("inventory_location")
            if inventory_location_id and updated.quality_status == ReceivedBatch.QualityStatus.RELEASED:
                inventory_location = self.tenant_object(
                    InventoryLocation,
                    inventory_location_id,
                    "inventory_location",
                )
                InventoryReceiptService.post_receipt(
                    tenant=self.current_tenant(),
                    received_batch=updated,
                    receiving_location=inventory_location,
                    actor=request.user,
                )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(ReceivedBatchSerializer(updated).data, status=status.HTTP_200_OK)


class ReceivingInspectionViewSet(BaseProcurementViewSet):
    model = ReceivingInspection
    serializer_class = ReceivingInspectionSerializer


class SupplierReturnViewSet(BaseProcurementViewSet):
    model = SupplierReturn
    serializer_class = SupplierReturnSerializer

    def create(self, request, *args, **kwargs):
        serializer = SupplierReturnCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.current_tenant()
        receipt = self.tenant_object(
            GoodsReceipt,
            serializer.validated_data["goods_receipt"],
            "goods_receipt",
        )
        try:
            supplier_return = SupplierReturnService.request_return(
                tenant=tenant,
                return_number=serializer.validated_data["return_number"],
                goods_receipt=receipt,
                reason=serializer.validated_data["reason"],
                requested_by=request.user,
            )
            for item in serializer.validated_data["lines"]:
                SupplierReturnService.add_line(
                    supplier_return=supplier_return,
                    sku=self.tenant_object(CommercialSKU, item["sku"], "sku"),
                    quantity=item["quantity"],
                    reason=serializer.validated_data["reason"],
                )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(self.get_serializer(supplier_return).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        try:
            supplier_return = SupplierReturnService.approve(
                supplier_return=self.get_object(),
                approver=request.user,
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(self.get_serializer(supplier_return).data)

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_return(self, request, pk=None):
        try:
            supplier_return = SupplierReturnService.dispatch(
                supplier_return=self.get_object()
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(self.get_serializer(supplier_return).data)


class ThreeWayMatchViewSet(BaseProcurementViewSet):
    model = ThreeWayMatch
    serializer_class = ThreeWayMatchSerializer

    def create(self, request, *args, **kwargs):
        serializer = ThreeWayMatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purchase_order = self.tenant_object(
            PurchaseOrder,
            serializer.validated_data["purchase_order"],
            "purchase_order",
        )
        goods_receipt = self.tenant_object(
            GoodsReceipt,
            serializer.validated_data["goods_receipt"],
            "goods_receipt",
        )
        try:
            match = ThreeWayMatchService.perform_three_way_match(
                purchase_order=purchase_order,
                goods_receipt=goods_receipt,
                invoice_reference=serializer.validated_data["invoice_reference"],
                invoice_amount=serializer.validated_data["invoice_amount"],
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            return _service_error(exc)
        return Response(self.get_serializer(match).data, status=status.HTTP_201_CREATED)
