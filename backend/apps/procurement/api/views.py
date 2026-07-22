from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.procurement.api.serializers import (
    GoodsReceiptSerializer,
    PurchaseOrderSerializer,
    PurchaseRequisitionSerializer,
    ReceivedBatchSerializer,
    ReceivingInspectionSerializer,
    SupplierProductAgreementSerializer,
    SupplierQualificationSerializer,
    SupplierReturnSerializer,
    SupplierSerializer,
    ThreeWayMatchSerializer,
)
from apps.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
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
    SupplierGovernanceService,
    SupplierQualificationService,
)


class BaseProcurementViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        tenant_id = get_current_tenant_id() or getattr(self.request, "tenant_id", None)
        if not tenant_id and hasattr(self.request.user, "tenant_id"):
            tenant_id = self.request.user.tenant_id
        if tenant_id:
            return self.model.objects.filter(tenant_id=tenant_id)
        return self.model.objects.none()

    def perform_create(self, serializer):
        tenant_id = get_current_tenant_id() or getattr(self.request, "tenant_id", None) or getattr(self.request.user, "tenant_id", None)
        serializer.save(tenant_id=tenant_id)


class SupplierViewSet(BaseProcurementViewSet):
    model = Supplier
    serializer_class = SupplierSerializer

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        supplier = self.get_object()
        updated = SupplierGovernanceService.approve_supplier(
            supplier=supplier, approver=request.user, reason=request.data.get("reason", "Approved via API")
        )
        return Response(SupplierSerializer(updated).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        supplier = self.get_object()
        reason = request.data.get("reason", "Suspended via API")
        updated = SupplierGovernanceService.suspend_supplier(supplier=supplier, reason=reason)
        return Response(SupplierSerializer(updated).data, status=status.HTTP_200_OK)


class SupplierQualificationViewSet(BaseProcurementViewSet):
    model = SupplierQualification
    serializer_class = SupplierQualificationSerializer

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request, pk=None):
        qual = self.get_object()
        updated = SupplierQualificationService.verify_qualification(qualification=qual, verifier=request.user)
        return Response(SupplierQualificationSerializer(updated).data, status=status.HTTP_200_OK)


class SupplierProductAgreementViewSet(BaseProcurementViewSet):
    model = SupplierProductAgreement
    serializer_class = SupplierProductAgreementSerializer


class PurchaseRequisitionViewSet(BaseProcurementViewSet):
    model = PurchaseRequisition
    serializer_class = PurchaseRequisitionSerializer

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        req = self.get_object()
        updated = PurchaseRequisitionService.approve_requisition(requisition=req, approver=request.user)
        return Response(PurchaseRequisitionSerializer(updated).data, status=status.HTTP_200_OK)


class PurchaseOrderViewSet(BaseProcurementViewSet):
    model = PurchaseOrder
    serializer_class = PurchaseOrderSerializer

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        po = self.get_object()
        updated = PurchaseOrderService.approve_po(purchase_order=po, approver=request.user)
        return Response(PurchaseOrderSerializer(updated).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request, pk=None):
        po = self.get_object()
        updated = PurchaseOrderService.send_po(purchase_order=po)
        return Response(PurchaseOrderSerializer(updated).data, status=status.HTTP_200_OK)


class GoodsReceiptViewSet(BaseProcurementViewSet):
    model = GoodsReceipt
    serializer_class = GoodsReceiptSerializer

    @action(detail=True, methods=["post"], url_path="close")
    def close_receipt(self, request, pk=None):
        grn = self.get_object()
        updated = GoodsReceivingService.close_goods_receipt(goods_receipt=grn)
        return Response(GoodsReceiptSerializer(updated).data, status=status.HTTP_200_OK)


class ReceivedBatchViewSet(BaseProcurementViewSet):
    model = ReceivedBatch
    serializer_class = ReceivedBatchSerializer

    @action(detail=True, methods=["post"], url_path="release")
    def release(self, request, pk=None):
        batch = self.get_object()
        reason = request.data.get("reason", "Released via API")
        updated = BatchReceivingService.release_batch(batch=batch, actor=request.user, reason=reason)
        return Response(ReceivedBatchSerializer(updated).data, status=status.HTTP_200_OK)


class ReceivingInspectionViewSet(BaseProcurementViewSet):
    model = ReceivingInspection
    serializer_class = ReceivingInspectionSerializer


class SupplierReturnViewSet(BaseProcurementViewSet):
    model = SupplierReturn
    serializer_class = SupplierReturnSerializer


class ThreeWayMatchViewSet(BaseProcurementViewSet):
    model = ThreeWayMatch
    serializer_class = ThreeWayMatchSerializer
