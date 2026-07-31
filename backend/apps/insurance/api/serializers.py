"""Insurance registry and read-workbench serialisers.

Insurer configuration is writable. Claim, remittance, and coverage state is
read-only by design: every transition runs through a service that enforces
authority, idempotency, and the transport/adjudication separation.

Membership numbers are masked. A claims list is a screen people leave open on a
shared desk, and the full number is an identifier for the member's whole
insurance relationship, not just this claim.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.insurance.models import (
    ClaimRejection,
    CoverageVerification,
    InsuranceCoverage,
    InsuranceRemittance,
    Insurer,
    PrescriptionClaim,
)


def mask_membership(value: str) -> str:
    """Show enough to recognise a member, not enough to impersonate one."""
    text = str(value or "")
    if len(text) <= 4:
        return "•" * len(text)
    return f"{'•' * (len(text) - 4)}{text[-4:]}"


class InsurerSerializer(serializers.ModelSerializer):
    adapter_registered = serializers.SerializerMethodField()

    class Meta:
        model = Insurer
        fields = [
            "id", "code", "name", "insurer_type", "integration_adapter",
            "environment", "status", "settlement_currency", "adapter_registered",
        ]

    def get_adapter_registered(self, insurer) -> bool:
        """Whether this insurer can actually transact.

        Configuration and capability are different things: SHA is configurable
        today and has no implemented adapter, and a workbench that showed it as
        ready would have somebody wondering why nothing sends.
        """
        from apps.insurance.adapters.base import ADAPTERS

        return insurer.integration_adapter in ADAPTERS

    def validate_code(self, value):
        code = value.strip().upper()
        if not code:
            raise serializers.ValidationError("Insurer code is required.")
        return code

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Insurer name is required.")
        return name


class CoverageSerializer(serializers.ModelSerializer):
    membership_number = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceCoverage
        fields = [
            "id", "membership_number", "relationship", "valid_from", "valid_to",
            "status", "remaining_limit", "copay_amount", "coinsurance_percentage",
        ]

    def get_membership_number(self, coverage) -> str:
        return mask_membership(coverage.member.membership_number)


class CoverageVerificationSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = CoverageVerification
        fields = [
            "id", "verification_reference", "is_eligible", "eligibility_status",
            "verified_at", "expires_at", "is_current",
        ]

    def get_is_current(self, verification) -> bool:
        # Computed rather than stored, so a list cannot show a stale check as
        # current merely because nobody has re-read it.
        from django.utils import timezone

        return verification.expires_at > timezone.now()


class ClaimSerializer(serializers.ModelSerializer):
    membership_number = serializers.SerializerMethodField()
    insurer_code = serializers.CharField(source="insurer.code", read_only=True)
    outstanding_amount = serializers.SerializerMethodField()
    is_receivable = serializers.SerializerMethodField()

    class Meta:
        model = PrescriptionClaim
        fields = [
            "id", "claim_number", "insurer_code", "membership_number",
            # All four state dimensions, never collapsed into one. A workbench
            # showing a single status is where transport acceptance starts
            # being read as payment.
            "submission_state", "adjudication_state", "payment_state",
            "reconciliation_state",
            "claimed_gross_amount", "approved_amount", "patient_copay_amount",
            "insurer_payable_amount", "paid_amount", "currency",
            "outstanding_amount", "is_receivable", "created_at",
        ]

    def get_membership_number(self, claim) -> str:
        return mask_membership(claim.member.membership_number)

    def get_outstanding_amount(self, claim) -> str:
        from apps.core.money import format_money
        from apps.insurance.services.remittance import InsuranceReceivableService

        return format_money(InsuranceReceivableService.outstanding(claim=claim)) or "0.00"

    def get_is_receivable(self, claim) -> bool:
        from apps.insurance.services.remittance import InsuranceReceivableService

        return InsuranceReceivableService.is_receivable(claim=claim)


class ClaimRejectionSerializer(serializers.ModelSerializer):
    claim_number = serializers.CharField(source="claim.claim_number", read_only=True)

    class Meta:
        model = ClaimRejection
        fields = [
            "id", "claim_number", "rejection_code", "reason_description",
            "resubmission_eligible", "operator_action", "resolved", "created_at",
        ]


class RemittanceSerializer(serializers.ModelSerializer):
    insurer_code = serializers.CharField(source="insurer.code", read_only=True)
    unmatched_lines = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceRemittance
        fields = [
            "id", "remittance_number", "insurer_code", "total_remitted_amount",
            "payment_reference", "remittance_date", "status", "unmatched_lines",
        ]

    def get_unmatched_lines(self, remittance) -> int:
        """Money that arrived and could not be placed.

        Surfaced on the list rather than buried in a detail view: it is the
        thing somebody has to act on.
        """
        return remittance.lines.filter(status="UNMATCHED").count()
