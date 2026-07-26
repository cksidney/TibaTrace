"""Coverage verification and eligibility.

Two rules govern this module.

**A membership number is not proof of cover.** A card can be valid, current and
correctly typed while the medicine on the counter is excluded, the annual limit
is spent, or the member is suspended. Treating "the number exists" as "the
insurer will pay" is how a provider dispenses on credit that was never extended.

**A stale verification is not a verification.** Eligibility answers expire
because cover changes: a member leaves an employer, a scheme suspends, a limit
runs out. Reusing yesterday's ELIGIBLE because it is convenient converts a
question into an assumption, so `expires_at` is checked on every read and there
is no path that skips it.
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from ..adapters.base import AdapterResult, BusinessState
from ..models import CoverageVerification, InsuranceCoverage

ZERO = Decimal("0.00")

#: How long an eligibility answer may be relied on. Short, because the facts
#: behind it change without anybody telling the pharmacy.
DEFAULT_VALIDITY = timedelta(hours=4)


class CoverageNotVerified(ValidationError):
    """No current verification exists."""


class CoverageNotEligible(ValidationError):
    """The insurer said no."""


class EligibilityStale(ValidationError):
    """The last verification has expired."""


class CoverageService:
    """Reads coverage facts. Never infers them."""

    @staticmethod
    def active_coverage(*, tenant_id, patient, insurer=None, service_date=None):
        """Coverage valid on the service date, or None.

        Filters on the date the medicine is supplied, not today. A claim
        submitted late is still judged against the date of service, and a
        coverage that lapsed in between did not cover it.
        """
        service_date = service_date or timezone.localdate()
        query = InsuranceCoverage.all_objects.filter(
            tenant_id=tenant_id,
            patient=patient,
            status=InsuranceCoverage.Status.ACTIVE,
            valid_from__lte=service_date,
            valid_to__gte=service_date,
        ).select_related("member", "scheme", "plan")
        if insurer is not None:
            query = query.filter(scheme__insurer=insurer)
        return query.first()

    @staticmethod
    def within_limit(*, coverage: InsuranceCoverage, amount: Decimal) -> bool:
        """Whether the remaining limit covers this amount.

        A limit of zero covers nothing. Where an insurer does not supply a
        remaining limit the field carries their last known figure, and this
        stays a check rather than becoming an assumption.
        """
        return Decimal(str(coverage.remaining_limit)) >= Decimal(str(amount))

    @staticmethod
    def match_member(*, tenant_id, membership_number: str, patient) -> InsuranceCoverage | None:
        """Match a patient to a coverage by membership number.

        Deliberately requires both. Matching on name alone would attach one
        patient's dispensing history to another person's insurance record, and
        names in this domain repeat constantly.
        """
        membership_number = str(membership_number or "").strip()
        if not membership_number:
            return None
        return (
            InsuranceCoverage.all_objects.filter(
                tenant_id=tenant_id,
                member__membership_number=membership_number,
                patient=patient,
            )
            .select_related("member")
            .first()
        )


class EligibilityService:
    """Asks the insurer, and records what they said and for how long."""

    @staticmethod
    def current_verification(*, tenant_id, member, patient) -> CoverageVerification | None:
        """The most recent unexpired verification, or None.

        Expiry is applied here rather than by the caller, so there is no path
        that reads a verification without checking whether it still holds.
        """
        now = timezone.now()
        return (
            CoverageVerification.all_objects.filter(
                tenant_id=tenant_id, member=member, patient=patient, expires_at__gt=now
            )
            .order_by("-verified_at")
            .first()
        )

    @classmethod
    def verify(cls, *, tenant_id, insurer, member, patient, adapter, service_date=None,
               validity: timedelta | None = None) -> CoverageVerification:
        """Ask the insurer and persist the answer.

        The answer is stored whether it is yes or no. A recorded refusal is what
        lets a pharmacy show the patient why cover was declined instead of
        simply failing.
        """
        request = {
            "member_number": member.membership_number,
            "patient_reference": str(patient.pk),
            "service_date": str(service_date or timezone.localdate()),
            "insurer": insurer.code,
        }
        result: AdapterResult = adapter.verify_coverage(request=request)

        if not result.reached_insurer:
            # We did not get an answer. That is not a "no", and it is certainly
            # not a "yes" -- it is an absence, and no verification is written.
            raise CoverageNotVerified(
                "The insurer could not be reached, so eligibility is unknown. "
                "Supply on insurance is not authorised."
            )

        eligible = result.business_state == BusinessState.APPROVED
        return CoverageVerification.all_objects.create(
            tenant_id=tenant_id,
            insurer=insurer,
            member=member,
            patient=patient,
            verification_reference=result.external_reference
            or f"VER-{secrets.token_hex(8)}",
            is_eligible=eligible,
            eligibility_status=result.response_code or result.business_state,
            expires_at=timezone.now() + (validity or DEFAULT_VALIDITY),
            raw_response_digest=result.raw_response_digest,
        )

    @classmethod
    def require_eligible(cls, *, tenant_id, member, patient) -> CoverageVerification:
        """The gate every insurance-funded supply passes through.

        Three distinct refusals, because they need three different responses
        from the counter: re-verify, tell the patient, or take cash.
        """
        verification = cls.current_verification(
            tenant_id=tenant_id, member=member, patient=patient
        )
        if verification is None:
            raise EligibilityStale(
                "Eligibility has not been verified, or the last check has expired. "
                "Re-verify before supplying on insurance."
            )
        if not verification.is_eligible:
            raise CoverageNotEligible(
                f"The insurer reported this member as not eligible "
                f"({verification.eligibility_status})."
            )
        return verification

    @staticmethod
    def record_manual_verification(*, tenant_id, insurer, member, patient, actor,
                                   reason: str, evidence: str,
                                   validity: timedelta | None = None) -> CoverageVerification:
        """Record a verification obtained outside the API.

        Insurers go down and pharmacies still dispense, so this path exists.
        It demands a reason, evidence and a named actor, and marks the result as
        manual: a manual verification carries the provider's risk, not the
        insurer's, and whoever accepted that risk must be identifiable.
        """
        if not str(reason).strip():
            raise ValidationError("A manual verification requires a reason.")
        if not str(evidence).strip():
            raise ValidationError(
                "A manual verification requires evidence, such as a call reference "
                "or portal screenshot identifier."
            )
        if actor is None:
            raise PermissionDenied("A manual verification requires a named actor.")

        return CoverageVerification.all_objects.create(
            tenant_id=tenant_id,
            insurer=insurer,
            member=member,
            patient=patient,
            verification_reference=f"MANUAL-{secrets.token_hex(8)}",
            is_eligible=True,
            # Distinguishable in every report from an insurer's own answer.
            eligibility_status="MANUAL_VERIFICATION",
            expires_at=timezone.now() + (validity or DEFAULT_VALIDITY),
            raw_response_digest="",
        )
