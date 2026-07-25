from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.identity.models import User
from apps.prescription.models import (
    DispensingEpisode,
    PosDeviceHealthRecord,
    PosShiftRecord,
)
from apps.prescription.pos_dispensing_api.serializers import (
    BatchVerificationRequestSerializer,
    CollectionConfirmRequestSerializer,
    ControlledVerifyRequestSerializer,
    CounsellingRecordSerializer,
    DeviceTelemetrySerializer,
    PartialDispenseRequestSerializer,
    PosDeviceHealthRecordSerializer,
    PosDispensingEpisodeSerializer,
    PosShiftRecordSerializer,
    ProcessPaymentRequestSerializer,
    ShiftEndSerializer,
    ShiftStartSerializer,
    TransitionStateRequestSerializer,
)
from apps.prescription.pos_dispensing_services import (
    PosBatchVerificationService,
    PosCollectionService,
    PosControlledMedicineService,
    PosCounsellingService,
    PosDispensingQueueService,
    PosPartialRepeatService,
    PosPaymentOrchestrationService,
    PosShiftService,
)


class PosDispensingViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only over episodes; all mutation goes through the gated actions.

    Deliberately not a ModelViewSet: a writable PATCH/PUT/DELETE here would let
    any authenticated caller set status/payment_status directly and bypass the
    clinical gates enforced by the service layer.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PosDispensingEpisodeSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            tenant_id = get_current_tenant_id()
            return DispensingEpisode.all_objects.filter(tenant_id=tenant_id)
        return DispensingEpisode.all_objects.filter(tenant=tenant)

    @action(detail=False, methods=["get"])
    def queue(self, request):
        tenant = getattr(self.request, "tenant", None)
        branch_id = request.query_params.get("branch")
        status_filter = request.query_params.get("status")

        qs = PosDispensingQueueService.get_queue(tenant=tenant, branch=branch_id, status=status_filter)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="transition-state")
    def transition_state(self, request, pk=None):
        episode = self.get_object()
        serializer = TransitionStateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            ep = PosDispensingQueueService.transition_state(
                episode=episode,
                new_status=data["new_status"],
                actor=request.user,
                notes=data.get("notes", ""),
            )
            return Response(self.get_serializer(ep).data)
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], url_path="verify-batch")
    def verify_batch(self, request):
        tenant = getattr(self.request, "tenant", None)
        serializer = BatchVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        res = PosBatchVerificationService.verify_batch(
            tenant=tenant,
            sku_id=data["sku_id"],
            batch_number=data["batch_number"],
            expiry_date=data.get("expiry_date"),
            quantity_scanned=data.get("quantity_scanned", 1),
        )
        return Response(res)

    @action(detail=True, methods=["post"], url_path="process-payment")
    def process_payment(self, request, pk=None):
        episode = self.get_object()
        serializer = ProcessPaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            res = PosPaymentOrchestrationService.process_payment(
                episode=episode,
                tender_type=data["tender_type"],
                paid_amount=data["paid_amount"],
                payment_reference=data.get("payment_reference", ""),
                cashier=request.user,
                idempotency_key=data["idempotency_key"],
            )
            return Response(res)
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="dispense-partial")
    def dispense_partial(self, request, pk=None):
        episode = self.get_object()
        serializer = PartialDispenseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            res = PosPartialRepeatService.dispense_partial(
                episode=episode,
                dispensing_line_id=data["dispensing_line_id"],
                quantity_supplied=data["quantity_supplied"],
                reason=data.get("reason", ""),
                actor=request.user,
                idempotency_key=data["idempotency_key"],
            )
            return Response(res)
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="verify-controlled")
    def verify_controlled(self, request, pk=None):
        episode = self.get_object()
        serializer = ControlledVerifyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        witness = None
        if data.get("witness_id"):
            tenant = getattr(self.request, "tenant", None)
            if tenant:
                witness = User.objects.filter(tenant=tenant, id=data["witness_id"]).first()

        try:
            res = PosControlledMedicineService.verify_controlled_authority(
                episode=episode,
                practitioner_id=data["practitioner_id"],
                collector_id_number=data["collector_id_number"],
                witness=witness,
                actor=request.user,
            )
            return Response(res)
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="record-counselling")
    def record_counselling(self, request, pk=None):
        episode = self.get_object()
        serializer = CounsellingRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            counselling = PosCounsellingService.record_counselling(
                episode=episode,
                pharmacist=request.user,
                medicine_explained=data["medicine_explained"],
                dosage_explained=data["dosage_explained"],
                storage_explained=data["storage_explained"],
                side_effects_discussed=data["side_effects_discussed"],
                interaction_advice_given=data["interaction_advice_given"],
                patient_acknowledged=data["patient_acknowledged"],
                notes=data.get("notes", ""),
            )
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": "COMPLETED", "counselling_id": str(counselling.id)})

    @action(detail=True, methods=["post"], url_path="confirm-collection")
    def confirm_collection(self, request, pk=None):
        episode = self.get_object()
        serializer = CollectionConfirmRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            supply = PosCollectionService.confirm_collection(
                episode=episode,
                collector_name=data["collector_name"],
                collector_id_number=data.get("collector_id_number", ""),
                collector_phone=data.get("collector_phone", ""),
                collector_relationship=data.get("collector_relationship", "SELF"),
                collection_proof_type=data.get("collection_proof_type", "SIGNATURE"),
                signature_ref=data.get("signature_ref", ""),
                actor=request.user,
                idempotency_key=data["idempotency_key"],
            )
            return Response({
                "status": "SUPPLIED",
                "supply_id": str(supply.id),
                "collected_at": episode.collected_at.isoformat(),
            })
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PosShiftViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PosShiftRecordSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            tenant_id = get_current_tenant_id()
            return PosShiftRecord.all_objects.filter(tenant_id=tenant_id)
        return PosShiftRecord.all_objects.filter(tenant=tenant)

    @action(detail=False, methods=["post"], url_path="start")
    def start_shift(self, request):
        tenant = getattr(self.request, "tenant", None)
        serializer = ShiftStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            shift = PosShiftService.start_shift(
                tenant=tenant,
                shift_number=data["shift_number"],
                cashier=request.user,
                pharmacist=request.user,
                controlled_start_count=data.get("controlled_start_count", 0),
                actor=request.user,
            )
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(shift).data)

    @action(detail=True, methods=["post"], url_path="end")
    def end_shift(self, request, pk=None):
        shift = self.get_object()
        serializer = ShiftEndSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            s = PosShiftService.end_shift(
                shift=shift,
                controlled_end_count=data.get("controlled_end_count", 0),
                declaration_notes=data.get("declaration_notes", ""),
                actor=request.user,
            )
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(s).data)


class PosDeviceHealthViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PosDeviceHealthRecordSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            tenant_id = get_current_tenant_id()
            return PosDeviceHealthRecord.all_objects.filter(tenant_id=tenant_id)
        return PosDeviceHealthRecord.all_objects.filter(tenant=tenant)

    @action(detail=False, methods=["post"], url_path="telemetry")
    def record_telemetry(self, request):
        tenant = getattr(self.request, "tenant", None)
        serializer = DeviceTelemetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        record, _ = PosDeviceHealthRecord.all_objects.update_or_create(
            tenant=tenant,
            device_id=data["device_id"],
            defaults={
                "device_type": data.get("device_type", "TERMINAL"),
                "status": data.get("status", "OK"),
                "printer_paper_level": data.get("printer_paper_level", "OK"),
                "scanner_connected": data.get("scanner_connected", True),
                "cash_drawer_open": data.get("cash_drawer_open", False),
                "network_latency_ms": data.get("network_latency_ms", 0),
                "battery_level_pct": data.get("battery_level_pct"),
                "storage_used_pct": data.get("storage_used_pct", 0),
            },
        )
        return Response(self.get_serializer(record).data)
