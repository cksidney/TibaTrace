from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.cds.models import ClinicalFinding
from apps.cds.services import ClinicalDecisionSupportService
from apps.core.api.viewsets import TenantModelViewSet
from apps.core.permissions import TenantCapabilityPermission, TenantRequired
from apps.inventory.models import InventoryLocation
from apps.medicines.models import CommercialSKU
from apps.organizations.models import Location
from apps.prescription.api.serializers import (
    ClinicalFindingSerializer,
    ClinicalSubstitutionSerializer,
    ClinicalWorkItemSerializer,
    DispensingAllocationSerializer,
    DispensingCheckSerializer,
    DispensingEpisodeCreateSerializer,
    DispensingEpisodeSerializer,
    DispensingLabelSerializer,
    DispensingLineSerializer,
    DispensingReservationSerializer,
    DispensingReserveSerializer,
    DispensingReversalSerializer,
    DispensingSupplySerializer,
    MedicineSupplySerializer,
    PatientCounsellingSerializer,
    PatientReturnReceiveSerializer,
    PatientReturnSerializer,
    PharmacistClinicalReviewSerializer,
    PharmacistInterventionSerializer,
    PharmacistVerificationSerializer,
    PrescriptionDispenseSerializer,
    PrescriptionItemSerializer,
    PrescriptionSerializer,
    PrescriptionValidationFindingSerializer,
)
from apps.prescription.models import (
    ClinicalWorkItem,
    DispensingEpisode,
    DispensingLine,
    MedicineSupply,
    MedicineSupplyLine,
    PatientReturn,
    PharmacistClinicalReview,
    PharmacistIntervention,
    Prescription,
    PrescriptionDispense,
    PrescriptionItem,
    PrescriptionValidationFinding,
)
from apps.prescription.services.clinical_dispensing import (
    ClinicalNotificationService,
    ClinicalSubstitutionService,
    DispensingAllocationService,
    DispensingCheckService,
    DispensingEpisodeService,
    DispensingLabelService,
    DispensingPreparationService,
    DispensingReservationService,
    DispensingReversalService,
    MedicineSupplyService,
    PatientCounsellingService,
    PatientReturnService,
    PharmacistInterventionService,
    PharmacistReviewService,
    PharmacistVerificationService,
    PrescriptionIntakeService,
    PrescriptionLifecycleService,
    PrescriptionValidationService,
)
from apps.prescription.services.dispensing_engine import DispensingEngine
from apps.prescription.services.qr_service import QRService
from apps.prescription.services.workflow import PrescriptionWorkflowService
from apps.sales.models import SalesOrder
from apps.tenancy.models import Tenant


def _idempotency_key(request):
    return str(
        request.headers.get("Idempotency-Key")
        or request.data.get("idempotency_key")
        or ""
    ).strip()


def _translate_domain_error(callable_):
    try:
        return callable_()
    except DjangoValidationError as exc:
        detail = getattr(exc, "message_dict", None) or getattr(
            exc,
            "messages",
            None,
        )
        raise ValidationError(detail or str(exc)) from exc


class ActionCapabilityMixin:
    action_capabilities = {}
    read_action_capabilities = {}

    def get_permissions(self):
        if self.request.method in {"GET", "HEAD", "OPTIONS"}:
            capability = self.read_action_capabilities.get(self.action)
            if capability:
                self.read_capability = capability
        else:
            capability = self.action_capabilities.get(self.action)
            if capability:
                self.write_capability = capability
        return super().get_permissions()


class ClinicalWorkItemViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClinicalWorkItemSerializer
    permission_classes = [IsAuthenticated, TenantRequired]
    search_fields = (
        "queue_type",
        "prescription__prescription_number",
        "dispensing_episode__dispensing_number",
        "branch__name",
    )
    ordering_fields = ("queue_type", "status", "due_at", "created_at")
    ordering = ("due_at", "created_at")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ClinicalWorkItem.all_objects.none()
        queryset = ClinicalWorkItem.all_objects.filter(
            tenant_id=self.request.tenant_id,
        ).select_related("prescription", "dispensing_episode", "branch")
        capabilities = getattr(
            self.request,
            "effective_capabilities",
            None,
        )
        if capabilities is None:
            capabilities = self.request.user.effective_capabilities(
                tenant_id=self.request.tenant_id,
            )
            self.request.effective_capabilities = capabilities
        if "*" not in capabilities:
            queryset = queryset.filter(required_capability__in=capabilities)
        allowed_branch_ids = (self.request.user.metadata or {}).get("branch_ids")
        if allowed_branch_ids:
            queryset = queryset.filter(branch_id__in=allowed_branch_ids)
        branch_id = self.request.query_params.get("branch")
        if branch_id:
            try:
                UUID(branch_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    {"branch": "A valid branch UUID is required."}
                ) from exc
            queryset = queryset.filter(branch_id=branch_id)
        queue_type = self.request.query_params.get("queue_type")
        if queue_type:
            queue_types = set(filter(None, queue_type.split(",")))
            valid_queue_types = {
                value for value, _label in ClinicalWorkItem.QUEUE_TYPE_CHOICES
            }
            if not queue_types.issubset(valid_queue_types):
                raise ValidationError(
                    {"queue_type": "One or more queue types are invalid."}
                )
            queryset = queryset.filter(queue_type__in=queue_types)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            statuses = set(filter(None, status_filter.split(",")))
            valid_statuses = {
                value for value, _label in ClinicalWorkItem.STATUS_CHOICES
            }
            if not statuses.issubset(valid_statuses):
                raise ValidationError(
                    {"status": "One or more queue statuses are invalid."}
                )
            queryset = queryset.filter(status__in=statuses)
        else:
            queryset = queryset.filter(status__in=["OPEN", "IN_PROGRESS"])
        return queryset


class PrescriptionViewSet(ActionCapabilityMixin, TenantModelViewSet):
    queryset = Prescription.all_objects.select_related(
        "patient",
        "practitioner",
        "organization",
        "location",
    ).prefetch_related("items")
    serializer_class = PrescriptionSerializer
    read_capability = "prescriptions.read"
    write_capability = "prescriptions.write"
    action_capabilities = {
        "create": "prescriptions.intake",
        "validation": "prescriptions.legal_validate",
        "clinical_review": "prescriptions.clinical_review",
        "verify": "prescriptions.pharmacist_verify",
        "hold": "prescriptions.clinical_review",
        "release_hold": "prescriptions.clinical_review",
        "cancel": "prescriptions.intake",
        "interventions": "prescriptions.intervention.create",
        "substitutions": "prescriptions.substitution.approve",
        "evaluate": "prescriptions.review",
        "transition": "prescriptions.write",
        "dispense": "dispensing.complete",
    }
    read_action_capabilities = {
        "findings": "cds.read",
        "interventions": "cds.read",
        "substitutions": "prescriptions.clinical_review",
    }
    search_fields = (
        "prescription_number",
        "external_prescription_reference",
        "patient__patient_number",
        "patient__internal_reference_id",
        "patient__first_name",
        "patient__last_name",
        "practitioner__registration_number",
    )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Prescription.all_objects.none()
        return self.queryset.filter(tenant_id=self.request.tenant_id)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_items = request.data.get("items") or []
        item_serializer = PrescriptionItemSerializer(data=raw_items, many=True)
        item_serializer.is_valid(raise_exception=True)
        prescription = _translate_domain_error(
            lambda: PrescriptionIntakeService.receive(
                tenant=Tenant.objects.get(id=request.tenant_id),
                actor=request.user,
                items=item_serializer.validated_data,
                **serializer.validated_data,
            )
        )
        output = self.get_serializer(prescription)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="validate")
    def validation(self, request, pk=None):
        prescription = _translate_domain_error(
            lambda: PrescriptionValidationService.validate(
                prescription=self.get_object(),
                actor=request.user,
            )
        )
        return Response(self.get_serializer(prescription).data)

    @action(detail=True, methods=["post"], url_path="clinical-review")
    def clinical_review(self, request, pk=None):
        review = _translate_domain_error(
            lambda: PharmacistReviewService.start(
                prescription=self.get_object(),
                actor=request.user,
                run_cds=request.data.get("run_cds", True),
            )
        )
        outcome = request.data.get("outcome")
        if outcome:
            review = _translate_domain_error(
                lambda: PharmacistReviewService.complete(
                    review=review,
                    actor=request.user,
                    outcome=outcome,
                    notes=request.data.get("notes", ""),
                )
            )
        return Response(PharmacistClinicalReviewSerializer(review).data)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        verification = _translate_domain_error(
            lambda: PharmacistVerificationService.verify(
                prescription=self.get_object(),
                actor=request.user,
                idempotency_key=_idempotency_key(request),
                decision=request.data.get("decision", "VERIFIED"),
                clinical_justification=request.data.get(
                    "clinical_justification",
                    "",
                ),
            )
        )
        return Response(PharmacistVerificationSerializer(verification).data)

    @action(detail=True, methods=["post"])
    def hold(self, request, pk=None):
        prescription = _translate_domain_error(
            lambda: PrescriptionLifecycleService.hold(
                prescription=self.get_object(),
                actor=request.user,
                reason=request.data.get("reason", ""),
            )
        )
        return Response(self.get_serializer(prescription).data)

    @action(detail=True, methods=["post"], url_path="release-hold")
    def release_hold(self, request, pk=None):
        prescription = _translate_domain_error(
            lambda: PrescriptionLifecycleService.release_hold(
                prescription=self.get_object(),
                actor=request.user,
                reason=request.data.get("reason", ""),
            )
        )
        return Response(self.get_serializer(prescription).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        prescription = _translate_domain_error(
            lambda: PrescriptionLifecycleService.cancel(
                prescription=self.get_object(),
                actor=request.user,
                reason=request.data.get("reason", ""),
            )
        )
        return Response(self.get_serializer(prescription).data)

    @action(detail=True, methods=["get"])
    def findings(self, request, pk=None):
        prescription = self.get_object()
        validation_findings = PrescriptionValidationFinding.all_objects.filter(
            tenant_id=request.tenant_id,
            prescription=prescription,
        ).order_by("-created_at")
        clinical_findings = ClinicalFinding.all_objects.filter(
            tenant_id=request.tenant_id,
            prescription=prescription,
        ).order_by("-created_at")
        return Response(
            {
                "validation": PrescriptionValidationFindingSerializer(
                    validation_findings,
                    many=True,
                ).data,
                "clinical": ClinicalFindingSerializer(
                    clinical_findings,
                    many=True,
                ).data,
            }
        )

    @action(detail=True, methods=["get", "post"])
    def interventions(self, request, pk=None):
        prescription = self.get_object()
        if request.method == "GET":
            queryset = PharmacistIntervention.all_objects.filter(
                tenant_id=request.tenant_id,
                prescription=prescription,
            ).order_by("-created_at")
            return Response(
                PharmacistInterventionSerializer(queryset, many=True).data
            )
        review = (
            PharmacistClinicalReview.all_objects.filter(
                tenant_id=request.tenant_id,
                prescription=prescription,
            )
            .order_by("-version")
            .first()
        )
        if not review:
            raise ValidationError("A pharmacist review is required.")
        values = {
            key: request.data[key]
            for key in (
                "prescription_item_id",
                "clinical_finding_id",
                "contacted_party",
                "contact_method",
                "original_instruction",
                "changed_instruction",
                "prescriber_authorization",
                "supporting_document_id",
            )
            if key in request.data
        }
        intervention = _translate_domain_error(
            lambda: PharmacistInterventionService.create(
                review=review,
                actor=request.user,
                intervention_type=request.data.get(
                    "intervention_type",
                    "CLARIFICATION",
                ),
                intervention_request=request.data.get(
                    "intervention_request",
                    "",
                ),
                **values,
            )
        )
        return Response(
            PharmacistInterventionSerializer(intervention).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"])
    def substitutions(self, request, pk=None):
        prescription = self.get_object()
        if request.method == "GET":
            return Response(
                ClinicalSubstitutionSerializer(
                    prescription.clinical_substitutions.all(),
                    many=True,
                ).data
            )
        item = PrescriptionItem.all_objects.filter(
            tenant_id=request.tenant_id,
            prescription=prescription,
            id=request.data.get("prescription_item_id"),
        ).first()
        proposed_sku = CommercialSKU.all_objects.filter(
            tenant_id=request.tenant_id,
            id=request.data.get("proposed_sku_id"),
        ).first()
        if not item or not proposed_sku:
            raise ValidationError(
                "Prescription item and tenant-owned proposed SKU are required."
            )
        substitution = _translate_domain_error(
            lambda: ClinicalSubstitutionService.propose(
                prescription_item=item,
                proposed_sku=proposed_sku,
                actor=request.user,
                equivalence_basis=request.data.get("equivalence_basis", ""),
                reason=request.data.get("reason", ""),
                price_impact=request.data.get("price_impact", 0),
                stock_reason=request.data.get("stock_reason", ""),
                prescriber_approved=request.data.get(
                    "prescriber_approved",
                    False,
                ),
                patient_consented=request.data.get("patient_consented", False),
                pharmacist_approved=request.data.get(
                    "pharmacist_approved",
                    False,
                ),
            )
        )
        return Response(
            ClinicalSubstitutionSerializer(substitution).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def evaluate(self, request, pk=None):
        if not request.user.has_capability(
            "prescriptions.review",
            tenant_id=request.tenant_id,
        ):
            return Response(
                {"detail": "Prescription review capability is required."},
                status=403,
            )
        evaluation = ClinicalDecisionSupportService.evaluate(
            prescription=self.get_object(),
            actor=request.user,
        )
        return Response(
            {
                "id": str(evaluation.id),
                "status": evaluation.status,
                "context_hash": evaluation.context_hash,
            }
        )

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        prescription = PrescriptionWorkflowService.transition(
            prescription_id=pk,
            tenant_id=request.tenant_id,
            actor=request.user,
            target_state=request.data.get("target_state"),
            reason=request.data.get("reason", ""),
            clinical_evaluation_id=request.data.get("clinical_evaluation_id"),
            payment_reference=request.data.get("payment_reference", ""),
        )
        return Response(self.get_serializer(prescription).data)

    @action(detail=True, methods=["post"])
    def dispense(self, request, pk=None):
        location = Location.all_objects.filter(
            id=request.data.get("location_id"),
            tenant_id=request.tenant_id,
        ).first()
        if not location:
            return Response(
                {"detail": "Location is unavailable in the active tenant."},
                status=404,
            )
        key = _idempotency_key(request)
        if not key:
            return Response({"detail": "Idempotency-Key is required."}, status=400)
        dispense = DispensingEngine.execute_dispense(
            prescription=self.get_object(),
            location=location,
            items_to_dispense=request.data.get("items") or [],
            user=request.user,
            idempotency_key=key,
        )
        return Response(
            PrescriptionDispenseSerializer(dispense).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"])
    def qr(self, request, pk=None):
        return Response({"payload": QRService.generate_payload(self.get_object())})


class DispensingEpisodeViewSet(ActionCapabilityMixin, TenantModelViewSet):
    queryset = DispensingEpisode.all_objects.select_related(
        "prescription",
        "patient",
        "branch",
        "pharmacy_location",
        "pharmacist",
    ).prefetch_related(
        "lines",
        "reservations",
        "allocations",
        "supplies__lines",
    )
    serializer_class = DispensingEpisodeSerializer
    read_capability = "dispensing.read"
    write_capability = "dispensing.prepare"
    action_capabilities = {
        "create": "dispensing.reserve",
        "reserve": "dispensing.reserve",
        "allocate": "dispensing.allocate",
        "prepare": "dispensing.prepare",
        "check": "dispensing.check",
        "label": "dispensing.prepare",
        "counsel": "dispensing.counsel",
        "supply": "dispensing.supply",
        "request_reversal": "dispensing.prepare",
        "reverse": "dispensing.reverse",
    }
    search_fields = (
        "dispensing_number",
        "prescription__prescription_number",
        "patient__patient_number",
    )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DispensingEpisode.all_objects.none()
        return self.queryset.filter(tenant_id=self.request.tenant_id)

    def create(self, request, *args, **kwargs):
        serializer = DispensingEpisodeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        prescription = Prescription.all_objects.filter(
            tenant_id=request.tenant_id,
            id=values.pop("prescription_id"),
        ).first()
        branch = Location.all_objects.filter(
            tenant_id=request.tenant_id,
            id=values.pop("branch_id"),
        ).first()
        pharmacy_location = InventoryLocation.all_objects.filter(
            tenant_id=request.tenant_id,
            id=values.pop("pharmacy_location_id"),
        ).first()
        sales_order_id = values.pop("sales_order_id", None)
        sales_order = (
            SalesOrder.all_objects.filter(
                tenant_id=request.tenant_id,
                id=sales_order_id,
            ).first()
            if sales_order_id
            else None
        )
        if not prescription or not branch or not pharmacy_location:
            raise ValidationError(
                "Tenant-owned prescription, branch, and pharmacy location are required."
            )
        episode = _translate_domain_error(
            lambda: DispensingEpisodeService.create(
                prescription=prescription,
                branch=branch,
                pharmacy_location=pharmacy_location,
                actor=request.user,
                sales_order=sales_order,
                idempotency_key=values.pop("idempotency_key", "")
                or _idempotency_key(request),
                **values,
            )
        )
        return Response(
            DispensingEpisodeSerializer(episode).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        serializer = DispensingReserveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        episode = self.get_object()
        item = PrescriptionItem.all_objects.filter(
            tenant_id=request.tenant_id,
            id=values.pop("prescription_item_id"),
            prescription=episode.prescription,
        ).first()
        substitute_sku_id = values.pop("substitute_sku_id", None)
        substitute_sku = (
            CommercialSKU.all_objects.filter(
                tenant_id=request.tenant_id,
                id=substitute_sku_id,
            ).first()
            if substitute_sku_id
            else None
        )
        if not item:
            raise ValidationError("Tenant-owned prescription item is required.")
        try:
            reservation = _translate_domain_error(
                lambda: DispensingReservationService.reserve(
                    episode=episode,
                    prescription_item=item,
                    actor=request.user,
                    substitute_sku=substitute_sku,
                    idempotency_key=values.pop("idempotency_key", "")
                    or _idempotency_key(request),
                    **values,
                )
            )
        except ValidationError as exc:
            if "Insufficient eligible stock" in str(exc.detail):
                ClinicalNotificationService.medicine_unavailable(
                    prescription=episode.prescription,
                )
            raise
        return Response(
            DispensingReservationSerializer(reservation).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        allocations = _translate_domain_error(
            lambda: DispensingAllocationService.allocate(
                episode=self.get_object(),
                actor=request.user,
            )
        )
        return Response(DispensingAllocationSerializer(allocations, many=True).data)

    @action(detail=True, methods=["post"])
    def prepare(self, request, pk=None):
        lines = _translate_domain_error(
            lambda: DispensingPreparationService.prepare(
                episode=self.get_object(),
                actor=request.user,
                quantities=request.data.get("quantities"),
            )
        )
        return Response(DispensingLineSerializer(lines, many=True).data)

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        final_check = _translate_domain_error(
            lambda: DispensingCheckService.check(
                episode=self.get_object(),
                actor=request.user,
                checklist=request.data.get("checklist") or {},
                notes=request.data.get("notes", ""),
            )
        )
        return Response(DispensingCheckSerializer(final_check).data)

    @action(detail=True, methods=["post"])
    def label(self, request, pk=None):
        line = DispensingLine.all_objects.filter(
            tenant_id=request.tenant_id,
            episode=self.get_object(),
            id=request.data.get("dispensing_line_id"),
        ).first()
        if not line:
            raise ValidationError("Tenant-owned dispensing line is required.")
        label = _translate_domain_error(
            lambda: DispensingLabelService.generate(
                dispensing_line=line,
                actor=request.user,
                label_size=request.data.get(
                    "label_size",
                    "PHARMACY_STANDARD",
                ),
            )
        )
        return Response(DispensingLabelSerializer(label).data)

    @action(detail=True, methods=["post"])
    def counsel(self, request, pk=None):
        values = {
            key: request.data.get(key)
            for key in (
                "topics",
                "warnings_explained",
                "administration_instructions",
                "storage_guidance",
                "adherence_advice",
                "side_effect_guidance",
                "missed_dose_guidance",
                "device_demonstration",
                "patient_questions",
                "language",
                "interpreter",
            )
            if key in request.data
        }
        counselling = _translate_domain_error(
            lambda: PatientCounsellingService.record(
                episode=self.get_object(),
                actor=request.user,
                counselling_required=request.data.get(
                    "counselling_required",
                    False,
                ),
                counselling_completed=request.data.get(
                    "counselling_completed",
                    False,
                ),
                refusal_reason=request.data.get("refusal_reason", ""),
                **values,
            )
        )
        return Response(PatientCounsellingSerializer(counselling).data)

    @action(detail=True, methods=["post"])
    def supply(self, request, pk=None):
        serializer = DispensingSupplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        supply = _translate_domain_error(
            lambda: MedicineSupplyService.supply(
                episode=self.get_object(),
                actor=request.user,
                idempotency_key=values.pop("idempotency_key", "")
                or _idempotency_key(request),
                **values,
            )
        )
        return Response(
            MedicineSupplySerializer(supply).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="request-reversal")
    def request_reversal(self, request, pk=None):
        supply_line = MedicineSupplyLine.all_objects.filter(
            tenant_id=request.tenant_id,
            supply__episode=self.get_object(),
            id=request.data.get("supply_line_id"),
        ).first()
        if not supply_line:
            raise ValidationError("Tenant-owned supply line is required.")
        work_item = _translate_domain_error(
            lambda: DispensingReversalService.request_approval(
                supply_line=supply_line,
                actor=request.user,
                reason=request.data.get("reason", ""),
            )
        )
        return Response(
            ClinicalWorkItemSerializer(work_item).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        supply_line = MedicineSupplyLine.all_objects.filter(
            tenant_id=request.tenant_id,
            supply__episode=self.get_object(),
            id=request.data.get("supply_line_id"),
        ).first()
        if not supply_line:
            raise ValidationError("Tenant-owned supply line is required.")
        reversal = _translate_domain_error(
            lambda: DispensingReversalService.reverse(
                supply_line=supply_line,
                actor=request.user,
                reason=request.data.get("reason", ""),
                idempotency_key=_idempotency_key(request),
                quantity=request.data.get("quantity"),
                physically_returned=request.data.get(
                    "physically_returned",
                    False,
                ),
                return_condition=request.data.get("return_condition", ""),
                inventory_eligibility=request.data.get(
                    "inventory_eligibility",
                    "QUARANTINE_REQUIRED",
                ),
            )
        )
        return Response(
            DispensingReversalSerializer(reversal).data,
            status=status.HTTP_201_CREATED,
        )


class PatientReturnViewSet(ActionCapabilityMixin, TenantModelViewSet):
    queryset = PatientReturn.all_objects.select_related(
        "supply",
        "patient",
        "quarantine_location",
        "received_by",
        "inspected_by",
    ).prefetch_related("lines")
    serializer_class = PatientReturnSerializer
    read_capability = "dispensing.read"
    write_capability = "dispensing.return.receive"
    action_capabilities = {
        "create": "dispensing.return.receive",
        "receive": "dispensing.return.receive",
        "inspect": "dispensing.return.quality",
    }
    http_method_names = ["get", "post", "head", "options"]
    search_fields = (
        "return_number",
        "supply__supply_number",
        "patient__patient_number",
    )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PatientReturn.all_objects.none()
        return self.queryset.filter(tenant_id=self.request.tenant_id)

    def create(self, request, *args, **kwargs):
        serializer = PatientReturnReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        supply = MedicineSupply.all_objects.filter(
            tenant_id=request.tenant_id,
            id=values.pop("supply_id"),
        ).first()
        quarantine_location = InventoryLocation.all_objects.filter(
            tenant_id=request.tenant_id,
            id=values.pop("quarantine_location_id"),
        ).first()
        if not supply or not quarantine_location:
            raise ValidationError(
                "Tenant-owned supply and quarantine location are required."
            )
        patient_return = _translate_domain_error(
            lambda: PatientReturnService.receive(
                supply=supply,
                actor=request.user,
                quarantine_location=quarantine_location,
                idempotency_key=values.pop("idempotency_key", "")
                or _idempotency_key(request),
                **values,
            )
        )
        return Response(
            PatientReturnSerializer(patient_return).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        return Response(PatientReturnSerializer(self.get_object()).data)

    @action(detail=True, methods=["post"])
    def inspect(self, request, pk=None):
        patient_return = _translate_domain_error(
            lambda: PatientReturnService.inspect(
                patient_return=self.get_object(),
                actor=request.user,
                quality_decision=request.data.get(
                    "quality_decision",
                    "RETAIN_IN_QUARANTINE",
                ),
                destruction_path=request.data.get("destruction_path", ""),
                refund_eligibility=request.data.get(
                    "refund_eligibility",
                    "NOT_ELIGIBLE",
                ),
            )
        )
        return Response(PatientReturnSerializer(patient_return).data)


class DispensingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PrescriptionDispenseSerializer
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "dispensing.read"
    write_capability = "dispensing.complete"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PrescriptionDispense.all_objects.none()
        return PrescriptionDispense.all_objects.filter(
            tenant_id=self.request.tenant_id
        ).select_related("prescription", "location", "dispensed_by")
