from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.identity.models import User
from apps.platform.client_alignment import RequireAlignedPosClientMixin
from apps.prescription.models import (
    DispensingEpisode,
    PosDeviceHealthRecord,
    PosShiftRecord,
)
from apps.prescription.pos_dispensing_api.serializers import (
    ActionReconciliationRequestSerializer,
    BatchVerificationRequestSerializer,
    CollectionConfirmRequestSerializer,
    ControlledVerifyRequestSerializer,
    CounsellingRecordSerializer,
    DeviceTelemetrySerializer,
    PartialDispenseRequestSerializer,
    PosDeviceHealthRecordSerializer,
    PosDispensingEpisodeSerializer,
    PosPrintJobSerializer,
    PosShiftRecordSerializer,
    PrintCancellationSerializer,
    PrintReprintSerializer,
    PrintResultSerializer,
    ProcessPaymentRequestSerializer,
    ShiftEndSerializer,
    ShiftStartSerializer,
    TransitionStateRequestSerializer,
)
from apps.prescription.pos_dispensing_services import (
    PosActionReconciliationService,
    PosBatchVerificationService,
    PosCollectionService,
    PosControlledMedicineService,
    PosCounsellingService,
    PosDispensingQueueService,
    PosPartialRepeatService,
    PosPaymentOrchestrationService,
    PosShiftService,
)
from apps.prescription.pos_permissions import (
    DISPENSING_READ_CAPABILITIES,
    PosReadCapabilityPermission,
    scope_to_actor_branches,
)
from apps.prescription.pos_printing_models import PosPrintJob
from apps.prescription.pos_printing_services import PosPrintJobService


class PosDispensingViewSet(RequireAlignedPosClientMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only over episodes; all mutation goes through the gated actions.

    Deliberately not a ModelViewSet: a writable PATCH/PUT/DELETE here would let
    any authenticated caller set status/payment_status directly and bypass the
    clinical gates enforced by the service layer.
    """

    permission_classes = [IsAuthenticated, PosReadCapabilityPermission]
    pos_read_capabilities = DISPENSING_READ_CAPABILITIES
    serializer_class = PosDispensingEpisodeSerializer

    @action(detail=True, methods=["get", "post"])
    def checkout(self, request, pk=None):
        from apps.prescription.checkout_api import checkout_response
        return checkout_response(request, self.get_object())

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            tenant_id = get_current_tenant_id()
            return scope_to_actor_branches(DispensingEpisode.all_objects.filter(tenant_id=tenant_id), self.request)
        return scope_to_actor_branches(DispensingEpisode.all_objects.filter(tenant=tenant), self.request)

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        # Reuse the canonical command, but retain POS version/activation gates
        # and return the till's minimum-necessary episode representation.
        from apps.prescription.api.views import DispensingEpisodeViewSet
        return DispensingEpisodeViewSet.reserve(self, request, pk)

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        from apps.prescription.api.views import DispensingEpisodeViewSet
        return DispensingEpisodeViewSet.allocate(self, request, pk)

    @action(detail=True, methods=["post"])
    def prepare(self, request, pk=None):
        from apps.prescription.api.views import DispensingEpisodeViewSet
        return DispensingEpisodeViewSet.prepare(self, request, pk)

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        from apps.prescription.api.views import DispensingEpisodeViewSet
        return DispensingEpisodeViewSet.check(self, request, pk)

    @action(detail=True, methods=["post"])
    def label(self, request, pk=None):
        from apps.prescription.api.views import DispensingEpisodeViewSet
        from apps.prescription.models import DispensingLabel
        from apps.prescription.pos_printing_services import PosPrintDocumentService
        response = DispensingEpisodeViewSet.label(self, request, pk)
        label = DispensingLabel.all_objects.get(tenant_id=request.tenant_id, pk=response.data["id"])
        device_id = request.headers.get("X-POS-Device-ID") or request.data.get("device_id", "")
        try:
            document, job = PosPrintDocumentService.issue_label(label=label, actor=request.user, device_id=device_id)
        except ValidationError as error:
            return Response({"error": str(error)}, status=400)
        return Response({"label_id": str(label.pk), "document_number": document.document_number,
                         "print_job_id": str(job.pk) if job else None})

    @action(detail=False, methods=["get"])
    def queue(self, request):
        # `request.tenant_id`, not `request.tenant`. TenantContextMiddleware only
        # ever sets the id, so the old `getattr(request, "tenant", None)` was
        # always None and the queue filtered on a null tenant -- it returned
        # zero episodes for every caller, always. The POS read that empty list
        # as "no patients waiting" and substituted a demo queue, which is why
        # the till never showed a real patient.
        tenant_id = get_current_tenant_id() or getattr(request, "tenant_id", None)
        branch_id = request.query_params.get("branch")
        status_filter = request.query_params.get("status")

        if tenant_id is None:
            return Response(
                {"detail": "No workspace is associated with this request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        qs = PosDispensingQueueService.get_queue(
            tenant=tenant_id, branch=branch_id, status=status_filter
        )
        qs = scope_to_actor_branches(qs, request)
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
        location = None
        if data.get("episode_id"):
            episode = self.get_queryset().filter(pk=data["episode_id"]).first()
            if not episode:
                return Response({"detail": "Episode not found within your workspace/branch."}, status=404)
            location = episode.pharmacy_location
        res = PosBatchVerificationService.verify_batch(
            tenant=tenant,
            sku_id=data["sku_id"],
            batch_number=data["batch_number"],
            expiry_date=data.get("expiry_date"),
            quantity_scanned=data.get("quantity_scanned", 1),
            location=location,
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
                device_id=data["device_id"],
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
            episode.refresh_from_db()
            return Response({
                "status": episode.status,
                "supply_id": str(supply.id),
                "collected_at": episode.collected_at.isoformat() if episode.collected_at else None,
            })
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="reconcile-action")
    def reconcile_action(self, request, pk=None):
        episode = self.get_object()
        serializer = ActionReconciliationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = PosActionReconciliationService.reconcile(
                episode=episode,
                action_type=serializer.validated_data["action_type"],
                idempotency_key=serializer.validated_data["idempotency_key"],
                actor=request.user,
            )
            return Response(result)
        except ValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class PosShiftViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, PosReadCapabilityPermission]
    pos_read_capabilities = ("pos.shift.manage", "pos.session.view", "pos.report.read", "dispensing.complete")
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
    permission_classes = [IsAuthenticated, PosReadCapabilityPermission]
    pos_read_capabilities = ("pos.shift.manage", "pos.device.manage", "pos.device.read")
    serializer_class = PosDeviceHealthRecordSerializer

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            tenant_id = get_current_tenant_id()
            return PosDeviceHealthRecord.all_objects.filter(tenant_id=tenant_id)
        return PosDeviceHealthRecord.all_objects.filter(tenant=tenant)

    @action(detail=False, methods=["post"], url_path="telemetry")
    def record_telemetry(self, request):
        from rest_framework.exceptions import PermissionDenied

        from apps.prescription.pos_permissions import has_any_capability
        if not has_any_capability(request.user, request.tenant_id, self.pos_read_capabilities):
            raise PermissionDenied("POS device authority is required to record telemetry.")
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


class PosPrintJobViewSet(viewsets.ReadOnlyModelViewSet):
    """Durable print-job queue; no direct document or job mutation is exposed."""

    permission_classes = [IsAuthenticated, PosReadCapabilityPermission]
    pos_read_capabilities = (
        "pos.document.print", "pos.document.reprint", "pos.document.read",
        "dispensing.prepare", "dispensing.complete",
    )
    serializer_class = PosPrintJobSerializer

    def get_queryset(self):
        tenant_id = get_current_tenant_id() or getattr(self.request, "tenant_id", None)
        queryset = PosPrintJob.all_objects.filter(tenant_id=tenant_id).select_related("document")
        queryset = scope_to_actor_branches(queryset, self.request)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        branch_id = self.request.query_params.get("branch_id")
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        device_id = self.request.query_params.get("device_id")
        if device_id:
            queryset = queryset.filter(device_id=device_id)
        return queryset.order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="select-transport")
    def select_transport(self, request, pk=None):
        try:
            job = PosPrintJobService.configure_transport(
                job=self.get_object(), actor=request.user,
                transport=request.data.get("transport", ""), printer=request.data.get("printer", ""),
                device_id=request.headers.get("X-POS-Device-ID") or request.data.get("device_id", ""),
            )
        except ValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=["post"])
    def snapshot(self, request, pk=None):
        from apps.audit.models import AuditEvent
        from apps.prescription.services.clinical_dispensing import _require_capability
        job = self.get_object()
        _require_capability(request.user, job.tenant_id, "pos.document.print")
        device_id = request.headers.get("X-POS-Device-ID") or request.data.get("device_id", "")
        if not device_id or job.device_id != device_id:
            return Response({"detail": "Document belongs to a different till installation."}, status=403)
        AuditEvent.all_objects.create(tenant_id=job.tenant_id, actor=request.user, action="POS_DOCUMENT_RENDER_VIEWED",
            model_name="PosPrintDocument", object_id=str(job.document_id), metadata={"job_id": str(job.pk), "device_id": device_id})
        return Response({"snapshot": job.document.snapshot, "document_hash": job.document.document_hash,
            "document_number": job.document.document_number, "copy_number": job.copy_number, "copy_classification": job.copy_classification})

    @action(detail=True, methods=["post"])
    def render(self, request, pk=None):
        try:
            job = PosPrintJobService.mark_rendered(job=self.get_object(), actor=request.user)
            return Response(self.get_serializer(job).data)
        except ValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        try:
            job = PosPrintJobService.start_attempt(job=self.get_object(), actor=request.user)
            return Response(self.get_serializer(job).data)
        except ValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def result(self, request, pk=None):
        serializer = PrintResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            job = PosPrintJobService.record_result(
                job=self.get_object(),
                actor=request.user,
                succeeded=data["succeeded"],
                failure_code=data.get("failure_code", ""),
                failure_message=data.get("failure_message", ""),
                retryable=data.get("retryable", True),
            )
            return Response(self.get_serializer(job).data)
        except ValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        try:
            job = PosPrintJobService.retry(job=self.get_object(), actor=request.user)
            return Response(self.get_serializer(job).data)
        except ValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        serializer = PrintCancellationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job = PosPrintJobService.cancel(
                job=self.get_object(),
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
            return Response(self.get_serializer(job).data)
        except ValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def reprint(self, request, pk=None):
        serializer = PrintReprintSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            job = PosPrintJobService.request_reprint(
                document=self.get_object().document,
                actor=request.user,
                reason=data["reason"],
                printer=data.get("printer", ""),
                transport=data.get("transport", PosPrintJob.Transport.SIMULATOR),
            )
            return Response(self.get_serializer(job).data, status=status.HTTP_201_CREATED)
        except ValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
