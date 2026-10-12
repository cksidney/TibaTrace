"""Insurance claims workbench and insurer registry.

Every endpoint here answers a question somebody has to act on: which claims are
approved but unpaid, which were rejected and can be resubmitted, which
remittance lines name no claim we hold.

Claim-state writes are not generic CRUD. Draft creation is a dedicated action
that starts from a tenant-owned medicine supply, validates current coverage and
insurer product mappings, then delegates construction to the claim service.
Submission, adjudication and payment remain separate service-governed states.

Every queryset is filtered by the requesting user's tenant. Filtering in a base
class rather than per-view means a new endpoint cannot leak by omission.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.audit.service import log_audit
from apps.insurance.models import (
    ClaimRejection,
    CoverageVerification,
    InsuranceCoverage,
    InsuranceRemittance,
    Insurer,
    MedicineClaimCodeMap,
    PrescriptionClaim,
)
from apps.medicines.models import CommercialSKU
from apps.patients.models import Patient
from apps.prescription.models import MedicineSupply, MedicineSupplyLine
from apps.tenancy.models import Tenant
from apps.workflows.service import emit_event

from .serializers import (
    ClaimRejectionSerializer,
    ClaimSerializer,
    CoverageSerializer,
    CoverageVerificationSerializer,
    DraftClaimFromSupplySerializer,
    InsuranceCoverageSetupSerializer,
    InsurerSerializer,
    RemittanceSerializer,
)


class TenantScopedReadOnly(viewsets.ReadOnlyModelViewSet):
    """Read-only, and scoped to the caller's tenant by construction.

    Subclasses set `model`; they do not write their own get_queryset. A
    per-view filter is a per-view opportunity to forget one.
    """

    permission_classes = [permissions.IsAuthenticated]
    model = None

    def tenant_id(self):
        tenant_id = getattr(self.request, "tenant_id", None) or getattr(
            getattr(self.request, "tenant", None), "pk", None
        )
        if tenant_id is None:
            tenant_id = getattr(self.request.user, "tenant_id", None)
        user_tenant_id = getattr(self.request.user, "tenant_id", None)
        if (
            tenant_id
            and user_tenant_id
            and str(tenant_id) != str(user_tenant_id)
            and not self.request.user.is_platform_admin
            and not self.request.user.is_superuser
        ):
            raise PermissionDenied("Requested tenant is outside the authenticated identity.")
        return tenant_id

    def get_queryset(self):
        tenant_id = self.tenant_id()
        if tenant_id is None:
            # No tenant, no rows. An unscoped read is how one pharmacy sees
            # another's claims.
            return self.model.all_objects.none()
        return self.model.all_objects.filter(tenant_id=tenant_id)


class InsurerViewSet(mixins.CreateModelMixin, TenantScopedReadOnly):
    model = Insurer
    serializer_class = InsurerSerializer

    def perform_create(self, serializer):
        tenant_id = self.tenant_id()
        if tenant_id is None:
            raise ValidationError({"tenant": "Select a tenant before configuring an insurer."})
        try:
            serializer.save(tenant_id=tenant_id)
        except IntegrityError as error:
            raise ValidationError(
                {"code": "This insurer code already exists for the selected tenant."}
            ) from error

    def _require_setup_authority(self, request):
        tenant_id = self.tenant_id()
        if not tenant_id or not request.user.has_capability("insurance.manage", tenant_id=tenant_id):
            raise PermissionDenied("Insurance setup requires the insurance.manage capability.")
        return tenant_id

    @action(detail=False, methods=["get"], url_path="setup-options")
    def setup_options(self, request):
        tenant_id = self._require_setup_authority(request)
        insurers = Insurer.all_objects.filter(
            tenant_id=tenant_id,
            status=Insurer.Status.ACTIVE,
            environment=Insurer.Environment.SANDBOX,
        ).order_by("name")
        patients = Patient.all_objects.filter(tenant_id=tenant_id, is_active=True).order_by("last_name", "first_name")[:500]
        skus = CommercialSKU.all_objects.filter(
            tenant_id=tenant_id,
            status=CommercialSKU.STATUS_ACTIVE,
        ).select_related("manufactured_product__clinical_product", "package_definition").order_by("display_name")[:1000]
        return Response({
            "insurers": InsurerSerializer(insurers, many=True).data,
            "patients": [
                {"id": str(patient.pk), "patient_number": patient.patient_number, "full_name": patient.full_name}
                for patient in patients
            ],
            "skus": [
                {
                    "id": str(sku.pk),
                    "sku_code": sku.sku_code,
                    "display_name": sku.display_name,
                    "unit": sku.package_definition.unit_of_measure,
                }
                for sku in skus
            ],
        })

    @action(detail=False, methods=["post"], url_path="setup-coverage")
    def setup_coverage(self, request):
        tenant_id = self._require_setup_authority(request)
        payload = InsuranceCoverageSetupSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        values = payload.validated_data
        insurer = Insurer.all_objects.filter(
            tenant_id=tenant_id,
            pk=values["insurer_id"],
            status=Insurer.Status.ACTIVE,
            environment=Insurer.Environment.SANDBOX,
        ).first()
        patient = Patient.all_objects.filter(tenant_id=tenant_id, pk=values["patient_id"], is_active=True).first()
        if insurer is None:
            raise ValidationError({"insurer_id": "Select an active sandbox insurer in this tenant."})
        if patient is None:
            raise ValidationError({"patient_id": "Select an active patient in this tenant."})
        sku_ids = [item["sku_id"] for item in values["item_mappings"]]
        skus = {
            sku.pk: sku
            for sku in CommercialSKU.all_objects.filter(
                tenant_id=tenant_id,
                pk__in=sku_ids,
                status=CommercialSKU.STATUS_ACTIVE,
            )
        }
        if len(skus) != len(set(sku_ids)):
            raise ValidationError({"item_mappings": "Every mapping must reference an active SKU in this tenant."})

        from apps.insurance.services.authoring import InsuranceSetupService

        try:
            with transaction.atomic():
                coverage = InsuranceSetupService.configure_member_coverage(
                    tenant=Tenant.objects.get(pk=tenant_id),
                    insurer=insurer,
                    scheme_code=values["scheme_code"],
                    scheme_name=values["scheme_name"],
                    plan_code=values["plan_code"],
                    plan_name=values["plan_name"],
                    patient=patient,
                    membership_number=values["membership_number"],
                    principal_name=values["principal_name"],
                    contact_phone=values.get("contact_phone", ""),
                    email=values.get("email", ""),
                    valid_from=values["valid_from"],
                    valid_to=values["valid_to"],
                    relationship=values["relationship"],
                    dependent_code=values["dependent_code"],
                    annual_limit=values["annual_limit"],
                    copay_amount=values["copay_amount"],
                    coinsurance_percentage=values["coinsurance_percentage"],
                    item_mappings=[
                        {**mapping, "sku": skus[mapping["sku_id"]]}
                        for mapping in values["item_mappings"]
                    ],
                    actor=request.user,
                )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": list(getattr(exc, "messages", [str(exc)]))}
            raise ValidationError(detail) from exc
        except IntegrityError as exc:
            raise ValidationError({"detail": "A scheme, plan, membership, or coverage record conflicts with existing setup."}) from exc
        coverage = InsuranceCoverage.all_objects.select_related("member", "scheme__insurer", "plan").get(pk=coverage.pk)
        return Response(CoverageSerializer(coverage).data, status=201)


class CoverageViewSet(TenantScopedReadOnly):
    model = InsuranceCoverage
    serializer_class = CoverageSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("member")
        patient_id = self.request.query_params.get("patient")
        if patient_id:
            queryset = queryset.filter(patient_id=patient_id)
        return queryset


class CoverageVerificationViewSet(TenantScopedReadOnly):
    model = CoverageVerification
    serializer_class = CoverageVerificationSerializer


class ClaimViewSet(TenantScopedReadOnly):
    model = PrescriptionClaim
    serializer_class = ClaimSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("insurer", "member")
        params = self.request.query_params
        for field in ("submission_state", "adjudication_state", "payment_state"):
            value = params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        if params.get("insurer"):
            queryset = queryset.filter(insurer_id=params["insurer"])
        return queryset.order_by("-created_at")

    def _require_claim_management(self, request):
        tenant_id = self.tenant_id()
        if not tenant_id or not request.user.has_capability("insurance.manage", tenant_id=tenant_id):
            raise PermissionDenied("Insurance claim intake requires the insurance.manage capability.")
        return tenant_id

    @action(detail=False, methods=["get"], url_path="intake-supplies")
    def intake_supplies(self, request):
        """Unclaimed supply events eligible for a governed claim draft.

        This deliberately starts from recorded supply, not the prescription or
        POS basket. Both pricing and product code mapping are explicit intake
        inputs, and the downstream constructor checks the supply again.
        """
        tenant_id = self._require_claim_management(request)
        from apps.insurance.api.serializers import mask_membership

        today = timezone.localdate()
        supplies = list(
            MedicineSupply.all_objects.filter(
                tenant_id=tenant_id,
                status__in=["PARTIAL", "COMPLETE"],
            )
            .filter(claims__isnull=True)
            .select_related("patient", "episode")
            .order_by("-supplied_at")[:200]
        )
        supply_ids = [supply.pk for supply in supplies]
        lines_by_supply = {}
        for line in MedicineSupplyLine.all_objects.filter(
            tenant_id=tenant_id,
            supply_id__in=supply_ids,
        ).select_related("supplied_sku"):
            lines_by_supply.setdefault(line.supply_id, []).append(line)
        patient_ids = {supply.patient_id for supply in supplies}
        coverages = list(
            InsuranceCoverage.all_objects.filter(
                tenant_id=tenant_id,
                patient_id__in=patient_ids,
                status=InsuranceCoverage.Status.ACTIVE,
                valid_from__lte=today,
                valid_to__gte=today,
                scheme__status="ACTIVE",
                scheme__insurer__status=Insurer.Status.ACTIVE,
            )
            .select_related("member", "scheme__insurer", "plan")
        )
        coverages_by_patient = {}
        for coverage in coverages:
            if coverage.plan.scheme_id == coverage.scheme_id:
                coverages_by_patient.setdefault(coverage.patient_id, []).append(coverage)

        sku_ids = {
            line.supplied_sku_id
            for supply in supplies
            for line in lines_by_supply.get(supply.pk, [])
        }
        code_maps = list(
            MedicineClaimCodeMap.all_objects.filter(
                tenant_id=tenant_id,
                sku_id__in=sku_ids,
                is_active=True,
                is_covered=True,
            ).select_related("insurer")
        )
        map_keys = {
            (mapping.insurer_id, mapping.sku_id)
            for mapping in code_maps
            if mapping.insurer_item_code.strip()
        }

        result = []
        for supply in supplies:
            lines = lines_by_supply.get(supply.pk, [])
            supplied_skus = {line.supplied_sku_id for line in lines}
            grouped_lines = {}
            for line in lines:
                grouped = grouped_lines.setdefault(
                    line.supplied_sku_id,
                    {
                        "sku_id": str(line.supplied_sku_id),
                        "sku_code": line.supplied_sku.sku_code,
                        "display_name": line.supplied_sku.display_name,
                        "quantity": Decimal("0"),
                        "unit": line.unit,
                    },
                )
                grouped["quantity"] += Decimal(str(line.quantity))
            coverage_options = []
            for coverage in coverages_by_patient.get(supply.patient_id, []):
                if all((coverage.scheme.insurer_id, sku_id) in map_keys for sku_id in supplied_skus):
                    coverage_options.append({
                        "id": str(coverage.pk),
                        "insurer_code": coverage.scheme.insurer.code,
                        "insurer_name": coverage.scheme.insurer.name,
                        "scheme_name": coverage.scheme.name,
                        "membership_number": mask_membership(coverage.member.membership_number),
                    })
            result.append({
                "id": str(supply.pk),
                "supply_number": supply.supply_number,
                "dispensing_number": supply.episode.dispensing_number,
                "supplied_at": supply.supplied_at,
                "status": supply.status,
                "coverage_options": coverage_options,
                "blocked_reason": (
                    "No current coverage with item codes for all supplied products."
                    if not coverage_options else ""
                ),
                "lines": [
                    {**line, "quantity": str(line["quantity"])}
                    for line in grouped_lines.values()
                ],
            })
        return Response(result)

    @action(detail=False, methods=["post"], url_path="from-supply")
    def create_from_supply(self, request):
        """Build a DRAFT claim from a real supply and current member coverage."""
        tenant_id = self._require_claim_management(request)
        intake = DraftClaimFromSupplySerializer(data=request.data)
        intake.is_valid(raise_exception=True)
        values = intake.validated_data
        unit_prices = values["unit_prices"]

        try:
            with transaction.atomic():
                supply = (
                    MedicineSupply.all_objects.select_for_update()
                    .filter(tenant_id=tenant_id, pk=values["supply_id"], status__in=["PARTIAL", "COMPLETE"])
                    .select_related("episode", "prescription")
                    .first()
                )
                if supply is None:
                    raise ValidationError({"supply_id": "A supplied medicine event in this tenant is required."})
                if PrescriptionClaim.all_objects.filter(tenant_id=tenant_id, supply=supply).exists():
                    raise ValidationError({"supply_id": "This supply already has a claim."})

                coverage = (
                    InsuranceCoverage.all_objects.select_for_update()
                    .filter(tenant_id=tenant_id, pk=values["coverage_id"])
                    .select_related("member", "scheme__insurer", "plan")
                    .first()
                )
                today = timezone.localdate()
                if (
                    coverage is None
                    or coverage.patient_id != supply.patient_id
                    or coverage.status != InsuranceCoverage.Status.ACTIVE
                    or coverage.valid_from > today
                    or coverage.valid_to < today
                    or coverage.scheme.status != "ACTIVE"
                    or coverage.scheme.insurer.status != Insurer.Status.ACTIVE
                    or coverage.plan.scheme_id != coverage.scheme_id
                ):
                    raise ValidationError({"coverage_id": "Select current active coverage for the supplied patient."})

                lines = list(
                    MedicineSupplyLine.all_objects.filter(
                        tenant_id=tenant_id,
                        supply=supply,
                    ).select_related("supplied_sku")
                )
                if not lines:
                    raise ValidationError({"supply_id": "The supplied event has no claimable medicine lines."})
                expected_skus = {str(line.supplied_sku_id) for line in lines}
                if set(unit_prices) != expected_skus:
                    raise ValidationError({
                        "unit_prices": "Enter one tariff unit price for every supplied product, with no extras."
                    })

                mappings = {
                    mapping.sku_id: mapping
                    for mapping in MedicineClaimCodeMap.all_objects.filter(
                        tenant_id=tenant_id,
                        insurer=coverage.scheme.insurer,
                        sku_id__in=[line.supplied_sku_id for line in lines],
                        is_active=True,
                        is_covered=True,
                    )
                }
                missing_codes = sorted({
                    line.supplied_sku.sku_code
                    for line in lines
                    if line.supplied_sku_id not in mappings
                    or not mappings[line.supplied_sku_id].insurer_item_code.strip()
                })
                if missing_codes:
                    raise ValidationError({
                        "coverage_id": "Map all supplied products to covered insurer codes before creating the claim: "
                        + ", ".join(missing_codes)
                    })

                from apps.insurance.services.claim_construction import ClaimConstructionService

                claim = ClaimConstructionService.build(
                    supply=supply,
                    coverage=coverage,
                    insurer=coverage.scheme.insurer,
                    scheme=coverage.scheme,
                    claim_number=values["claim_number"],
                    unit_prices=unit_prices,
                )
                log_audit(
                    tenant_id=tenant_id,
                    action="INSURANCE_CLAIM_DRAFT_CREATED",
                    model_name="PrescriptionClaim",
                    object_id=claim.pk,
                    actor_id=request.user.pk,
                    metadata={
                        "supply_id": str(supply.pk),
                        "coverage_id": str(coverage.pk),
                        "pricing_reference": values["pricing_reference"],
                        "unit_prices": {key: str(value) for key, value in unit_prices.items()},
                    },
                )
                emit_event(
                    tenant_id=tenant_id,
                    aggregate_type="PrescriptionClaim",
                    aggregate_id=claim.pk,
                    event_type="insurance.claim.draft_created",
                    payload={"claim_id": str(claim.pk), "supply_id": str(supply.pk)},
                    auto_process=False,
                )
        except IntegrityError as error:
            raise ValidationError({"claim_number": "That claim reference already exists for this tenant."}) from error

        return Response(self.get_serializer(claim).data, status=201)

    @action(detail=False, methods=["get"], url_path="approved-unpaid")
    def approved_unpaid(self, request):
        """Claims the insurer agreed to pay and has not paid.

        The single most useful list in the workbench: it is the money owed, and
        it is the list nobody assembles by hand often enough.
        """
        queryset = self.get_queryset().filter(
            adjudication_state__in=[
                PrescriptionClaim.AdjudicationState.APPROVED,
                PrescriptionClaim.AdjudicationState.PARTIALLY_APPROVED,
            ],
            payment_state__in=[
                PrescriptionClaim.PaymentState.UNPAID,
                PrescriptionClaim.PaymentState.PARTIALLY_PAID,
            ],
        )
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["get"], url_path="awaiting-decision")
    def awaiting_decision(self, request):
        """Sent, acknowledged, and still undecided.

        Kept separate from approved-unpaid because they are different problems:
        this one is chased with the insurer, that one is chased for payment.
        Merging them is how transport acceptance starts looking like a debt.
        """
        queryset = self.get_queryset().filter(
            submission_state__in=[
                PrescriptionClaim.SubmissionState.SUBMITTED,
                PrescriptionClaim.SubmissionState.TRANSPORT_ACCEPTED,
            ],
            adjudication_state=PrescriptionClaim.AdjudicationState.PENDING,
        )
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["get"], url_path="needs-attention")
    def needs_attention(self, request):
        """Everything blocked on somebody here rather than on the insurer."""
        queryset = self.get_queryset().filter(
            Q(submission_state=PrescriptionClaim.SubmissionState.VALIDATION_FAILED)
            | Q(submission_state=PrescriptionClaim.SubmissionState.TRANSPORT_REJECTED)
            | Q(adjudication_state=PrescriptionClaim.AdjudicationState.REJECTED)
            | Q(adjudication_state=PrescriptionClaim.AdjudicationState.MORE_INFO_REQUIRED)
        )
        return Response(self.get_serializer(queryset, many=True).data)


class ClaimRejectionViewSet(TenantScopedReadOnly):
    model = ClaimRejection
    serializer_class = ClaimRejectionSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("claim")
        if self.request.query_params.get("unresolved") == "true":
            queryset = queryset.filter(resolved=False)
        return queryset


class RemittanceViewSet(TenantScopedReadOnly):
    model = InsuranceRemittance
    serializer_class = RemittanceSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("insurer").order_by("-remittance_date")
