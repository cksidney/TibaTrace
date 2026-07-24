from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.sales.api.serializers import (
    CustomerPriceAgreementSerializer,
    DeliveryRecordSerializer,
    DispatchOrderSerializer,
    PackageSerializer,
    PackingSessionSerializer,
    PickingTaskSerializer,
    PickingWaveSerializer,
    PriceListEntrySerializer,
    PriceListSerializer,
    PromotionRuleSerializer,
    QuotationSerializer,
    SalesOrderAllocationSerializer,
    SalesOrderHoldSerializer,
    SalesOrderSerializer,
    SalesReturnAuthorizationSerializer,
)
from apps.sales.models import (
    CustomerPriceAgreement,
    DeliveryRecord,
    DispatchOrder,
    Package,
    PackingSession,
    PickingTask,
    PickingWave,
    PriceList,
    PriceListEntry,
    PromotionRule,
    Quotation,
    SalesOrder,
    SalesOrderAllocation,
    SalesOrderHold,
    SalesReturnAuthorization,
)
from apps.sales.services import (
    DeliveryService,
    DispatchService,
    PackingService,
    PickingService,
    PickingWaveService,
    QuotationService,
    SalesAllocationService,
    SalesApprovalService,
    SalesOrderService,
    SalesReservationService,
    SalesReturnService,
)


class BaseSalesViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        tenant_id = get_current_tenant_id() or getattr(self.request, "tenant_id", None)
        if not tenant_id and hasattr(self.request.user, "tenant_id"):
            tenant_id = self.request.user.tenant_id
        if tenant_id:
            return self.model.objects.filter(tenant_id=tenant_id)
        return self.model.objects.none()

    def perform_create(self, serializer):
        tenant_id = (
            get_current_tenant_id()
            or getattr(self.request, "tenant_id", None)
            or getattr(self.request.user, "tenant_id", None)
        )
        serializer.save(tenant_id=tenant_id)


class PriceListViewSet(BaseSalesViewSet):
    model = PriceList
    serializer_class = PriceListSerializer


class PriceListEntryViewSet(BaseSalesViewSet):
    model = PriceListEntry
    serializer_class = PriceListEntrySerializer


class PromotionRuleViewSet(BaseSalesViewSet):
    model = PromotionRule
    serializer_class = PromotionRuleSerializer


class CustomerPriceAgreementViewSet(BaseSalesViewSet):
    model = CustomerPriceAgreement
    serializer_class = CustomerPriceAgreementSerializer


class QuotationViewSet(BaseSalesViewSet):
    model = Quotation
    serializer_class = QuotationSerializer

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        obj = self.get_object()
        QuotationService.submit_quotation(quotation=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        QuotationService.approve_quotation(quotation=obj, approver=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        obj = self.get_object()
        QuotationService.send_quotation(quotation=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        obj = self.get_object()
        QuotationService.accept_quotation(quotation=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        obj = self.get_object()
        order = QuotationService.convert_quotation(quotation=obj, actor=request.user)
        return Response({"sales_order_id": order.id}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        obj = self.get_object()
        QuotationService.revise_quotation(
            quotation=obj,
            changed_fields=request.data.get("changed_fields", []),
            new_values=request.data.get("new_values", {}),
            reason=request.data.get("reason", ""),
            actor=request.user,
        )
        return Response(self.get_serializer(obj).data)


class SalesOrderViewSet(BaseSalesViewSet):
    model = SalesOrder
    serializer_class = SalesOrderSerializer

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        obj = self.get_object()
        SalesOrderService.submit_order(sales_order=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        SalesApprovalService.approve_order(sales_order=obj, approver=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def hold(self, request, pk=None):
        obj = self.get_object()
        SalesApprovalService.place_hold(
            sales_order=obj,
            hold_type=request.data.get("hold_type"),
            reason=request.data.get("reason", ""),
            placed_by=request.user,
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def release_hold(self, request, pk=None):
        obj = self.get_object()
        hold_id = request.data.get("hold_id")
        hold = SalesOrderHold.objects.get(id=hold_id, sales_order=obj, tenant=obj.tenant)
        SalesApprovalService.release_hold(
            hold=hold, released_by=request.user, release_reason=request.data.get("release_reason", "")
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        obj = self.get_object()
        SalesReservationService.reserve_order(sales_order=obj, actor=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        obj = self.get_object()
        SalesAllocationService.allocate_order(sales_order=obj, actor=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        obj = self.get_object()
        result = SalesOrderService.cancel_order(
            sales_order=obj, reason=request.data.get("reason", ""), actor=request.user
        )
        return Response(self.get_serializer(result).data)


class SalesOrderHoldViewSet(BaseSalesViewSet):
    model = SalesOrderHold
    serializer_class = SalesOrderHoldSerializer


class SalesOrderAllocationViewSet(BaseSalesViewSet):
    model = SalesOrderAllocation
    serializer_class = SalesOrderAllocationSerializer


class PickingWaveViewSet(BaseSalesViewSet):
    model = PickingWave
    serializer_class = PickingWaveSerializer

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        obj = self.get_object()
        PickingWaveService.release_wave(wave=obj)
        return Response(self.get_serializer(obj).data)


class PickingTaskViewSet(BaseSalesViewSet):
    model = PickingTask
    serializer_class = PickingTaskSerializer

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        obj = self.get_object()
        result = PickingService.assign_task(task=obj, picker=request.user)
        return Response(self.get_serializer(result).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        obj = self.get_object()
        PickingService.start_task(task=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def record(self, request, pk=None):
        obj = self.get_object()
        PickingService.record_pick(
            task=obj,
            picked_quantity=request.data.get("picked_quantity", 0),
            short_quantity=request.data.get("short_quantity", 0),
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        obj = self.get_object()
        PickingService.verify_pick(task=obj, verifier=request.user)
        return Response(self.get_serializer(obj).data)


class PackingSessionViewSet(BaseSalesViewSet):
    model = PackingSession
    serializer_class = PackingSessionSerializer


class PackageViewSet(BaseSalesViewSet):
    model = Package
    serializer_class = PackageSerializer

    @action(detail=True, methods=["post"])
    def seal(self, request, pk=None):
        obj = self.get_object()
        PackingService.seal_package(package=obj, seal_number=request.data.get("seal_number", ""), verifier=request.user)
        return Response(self.get_serializer(obj).data)


class DispatchOrderViewSet(BaseSalesViewSet):
    model = DispatchOrder
    serializer_class = DispatchOrderSerializer

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        DispatchService.approve_dispatch(dispatch=obj, approver=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def load(self, request, pk=None):
        obj = self.get_object()
        DispatchService.load_dispatch(dispatch=obj, packages=request.data.get("packages", []), loaded_by=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_action(self, request, pk=None):
        obj = self.get_object()
        result = DispatchService.dispatch_order(dispatch=obj, dispatched_by=request.user)
        return Response(self.get_serializer(result).data)


class DeliveryRecordViewSet(BaseSalesViewSet):
    model = DeliveryRecord
    serializer_class = DeliveryRecordSerializer

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        obj = self.get_object()
        result = DeliveryService.confirm_delivery(
            dispatch=obj.dispatch_order,
            recipient_name=request.data.get("recipient_name", ""),
            recipient_role=request.data.get("recipient_role", ""),
            recipient_phone=request.data.get("recipient_phone", ""),
            proof_type=request.data.get("proof_type", ""),
            signature_ref=request.data.get("signature_ref", ""),
            photo_ref=request.data.get("photo_ref", ""),
            coordinates=request.data.get("coordinates", ""),
            temperature_evidence=request.data.get("temperature_evidence", ""),
            delivery_notes=request.data.get("delivery_notes", ""),
            recorded_by=request.user,
            delivery_lines_data=request.data.get("delivery_lines_data", []),
            idempotency_key=request.data.get("idempotency_key"),
        )
        return Response(self.get_serializer(result).data)

    @action(detail=True, methods=["post"])
    def fail(self, request, pk=None):
        obj = self.get_object()
        result = DeliveryService.record_failed_delivery(
            dispatch=obj.dispatch_order,
            failure_reason=request.data.get("failure_reason", ""),
            recorded_by=request.user,
            idempotency_key=request.data.get("idempotency_key"),
        )
        return Response(self.get_serializer(result).data)


class SalesReturnAuthorizationViewSet(BaseSalesViewSet):
    model = SalesReturnAuthorization
    serializer_class = SalesReturnAuthorizationSerializer

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        SalesReturnService.approve_return(return_auth=obj, approver=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        obj = self.get_object()
        SalesReturnService.receive_return(
            return_auth=obj,
            received_quantities=request.data.get("received_quantities", {}),
            received_by=request.user,
        )
        return Response(self.get_serializer(obj).data)
