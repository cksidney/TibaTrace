"""Insurance claims workbench and insurer registry.

Every endpoint here answers a question somebody has to act on: which claims are
approved but unpaid, which were rejected and can be resubmitted, which
remittance lines name no claim we hold.

Claim-state writes are deliberately absent. Insurer registration is the only
generic create path; claim state still moves through services that enforce
authority, idempotency and the separation between transport acceptance,
adjudication and payment.

Every queryset is filtered by the requesting user's tenant. Filtering in a base
class rather than per-view means a new endpoint cannot leak by omission.
"""
from __future__ import annotations

from django.db import IntegrityError
from django.db.models import Q
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.insurance.models import (
    ClaimRejection,
    CoverageVerification,
    InsuranceCoverage,
    InsuranceRemittance,
    Insurer,
    PrescriptionClaim,
)

from .serializers import (
    ClaimRejectionSerializer,
    ClaimSerializer,
    CoverageSerializer,
    CoverageVerificationSerializer,
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
