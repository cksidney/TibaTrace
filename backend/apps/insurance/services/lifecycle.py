"""Rejection handling, resubmission and reversal.

The rule running through all three: **a correction adds a record, it never edits
the one that was wrong.**

An insurer holds a copy of what we sent them. Editing our copy so the two no
longer agree destroys the only evidence of what was actually claimed, which is
exactly what an auditor or a fraud investigation needs. So a resubmission is a
new claim linked to the original, a reversal references the claim it reverses,
and neither touches the original's amounts or its adjudication.

The second rule: **a reversal is not a deletion.** Medicine was supplied and a
claim was made. If either was wrong, the correct record is that it happened and
was then reversed -- not that it never happened.
"""
from __future__ import annotations

import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from ..adapters.base import AdapterResult, BusinessState
from ..models import (
    ClaimRejection,
    ClaimResubmission,
    ClaimReversal,
    PrescriptionClaim,
    PrescriptionClaimLine,
)

ZERO = Decimal("0.00")
PENNY = Decimal("0.01")


def money(value) -> Decimal:
    if value is None:
        return ZERO
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


#: Insurer codes mapped to a vocabulary the workbench can group and count.
#: Without this every insurer's private code becomes its own category and the
#: rejection report is a list of one-offs nobody can act on.
CANONICAL_REJECTION_REASONS: dict[str, str] = {
    "MEMBER_INELIGIBLE": "MEMBER_INELIGIBLE",
    "NOT_ELIGIBLE": "MEMBER_INELIGIBLE",
    "COVERAGE_EXPIRED": "COVERAGE_EXPIRED",
    "NON_FORMULARY": "MEDICINE_NOT_COVERED",
    "ITEM_NOT_COVERED": "MEDICINE_NOT_COVERED",
    "PREAUTH_MISSING": "PREAUTHORISATION_MISSING",
    "AUTH_EXPIRED": "AUTHORISATION_EXPIRED",
    "QUANTITY_LIMIT": "QUANTITY_EXCEEDED",
    "DUPLICATE_SUBMISSION": "DUPLICATE_CLAIM",
    "INVALID_CODE": "INVALID_CODE",
    "TARIFF_LIMIT": "TARIFF_MISMATCH",
    "ATTACHMENT_REQUIRED": "MISSING_ATTACHMENT",
    "PROVIDER_NOT_CONTRACTED": "PROVIDER_NOT_CONTRACTED",
}

#: Rejections a corrected resubmission can plausibly fix. The rest need
#: something else to change first -- a mapping, a contract, an authorisation --
#: and resubmitting them unchanged just produces the same rejection.
RESUBMITTABLE_REASONS = frozenset(
    {
        "INVALID_CODE",
        "MISSING_ATTACHMENT",
        "TARIFF_MISMATCH",
        "QUANTITY_EXCEEDED",
        "PREAUTHORISATION_MISSING",
    }
)


def canonical_reason(insurer_code: str) -> str:
    """Map an insurer's code to the shared vocabulary.

    Unknown codes are preserved rather than bucketed as OTHER, so a new insurer
    code shows up as itself and gets mapped deliberately instead of disappearing
    into a catch-all.
    """
    code = str(insurer_code or "").strip().upper()
    return CANONICAL_REJECTION_REASONS.get(code, code or "UNSPECIFIED")


class NotResubmittable(ValidationError):
    """This rejection will not be fixed by sending the same claim again."""


class RejectionService:
    """Records why an insurer refused, in terms the workbench can group."""

    @staticmethod
    def record(*, claim: PrescriptionClaim, result: AdapterResult) -> ClaimRejection:
        if result.business_state != BusinessState.REJECTED:
            raise ValidationError("Only a rejection may be recorded as one.")

        reason = canonical_reason(result.response_code)
        return ClaimRejection.all_objects.create(
            tenant_id=claim.tenant_id,
            claim=claim,
            rejection_code=reason,
            reason_description=result.response_message or result.response_code,
            resubmission_eligible=reason in RESUBMITTABLE_REASONS,
        )

    @staticmethod
    def open_rejections(*, tenant_id, claim=None):
        query = ClaimRejection.all_objects.filter(tenant_id=tenant_id, resolved=False)
        if claim is not None:
            query = query.filter(claim=claim)
        return query


class ClaimResubmissionService:
    """Creates a corrected claim without disturbing the rejected one."""

    @classmethod
    @transaction.atomic
    def resubmit(cls, *, original: PrescriptionClaim, actor, reason: str,
                 claim_number: str | None = None) -> PrescriptionClaim:
        """Copy the claim, link the copy to the original, leave the original alone.

        The insurer holds a copy of what we sent. Editing ours so the two
        disagree destroys the evidence of what was actually claimed.
        """
        if not str(reason).strip():
            raise ValidationError("A resubmission requires a reason.")
        if actor is None:
            raise PermissionDenied("A resubmission requires a named actor.")

        if original.adjudication_state != PrescriptionClaim.AdjudicationState.REJECTED:
            raise NotResubmittable(
                "Only a rejected claim may be resubmitted. "
                "Correct a pending claim by waiting for its decision, or reverse it."
            )

        blocking = [
            rejection
            for rejection in ClaimRejection.all_objects.filter(
                tenant_id=original.tenant_id, claim=original, resolved=False
            )
            if not rejection.resubmission_eligible
        ]
        if blocking:
            raise NotResubmittable(
                {
                    "rejections": [
                        f"{rejection.rejection_code} will not be resolved by resubmitting "
                        "the same claim. Fix the underlying cause first."
                        for rejection in blocking
                    ]
                }
            )

        replacement = PrescriptionClaim.all_objects.create(
            tenant_id=original.tenant_id,
            claim_number=claim_number or f"{original.claim_number}-R{secrets.token_hex(3)}",
            episode=original.episode,
            prescription=original.prescription,
            # Same supply. A resubmission re-states a claim for medicine already
            # dispensed; it never re-dispenses anything.
            supply=original.supply,
            patient=original.patient,
            member=original.member,
            insurer=original.insurer,
            scheme=original.scheme,
            preauthorisation=original.preauthorisation,
            claimed_gross_amount=original.claimed_gross_amount,
            claimed_net_amount=original.claimed_net_amount,
            patient_copay_amount=original.patient_copay_amount,
            currency=original.currency,
            submission_state=PrescriptionClaim.SubmissionState.DRAFT,
            adjudication_state=PrescriptionClaim.AdjudicationState.PENDING,
        )

        for line in PrescriptionClaimLine.all_objects.filter(
            tenant_id=original.tenant_id, claim=original
        ):
            PrescriptionClaimLine.all_objects.create(
                tenant_id=original.tenant_id,
                claim=replacement,
                prescription_line=line.prescription_line,
                sku=line.sku,
                insurer_item_code=line.insurer_item_code,
                quantity=line.quantity,
                unit_price=line.unit_price,
                claimed_amount=line.claimed_amount,
                status="DRAFT",
            )

        ClaimResubmission.all_objects.create(
            tenant_id=original.tenant_id,
            original_claim=original,
            new_claim=replacement,
            resubmission_reason=reason,
            resubmitted_by=actor,
        )

        ClaimRejection.all_objects.filter(
            tenant_id=original.tenant_id, claim=original, resolved=False
        ).update(resolved=True, operator_action=f"Resubmitted as {replacement.claim_number}")

        return replacement

    @staticmethod
    def chain(*, claim: PrescriptionClaim) -> list[str]:
        """Every claim number in this claim's resubmission history."""
        numbers = [claim.claim_number]
        current = claim
        while True:
            link = ClaimResubmission.all_objects.filter(
                tenant_id=claim.tenant_id, new_claim=current
            ).select_related("original_claim").first()
            if link is None:
                break
            current = link.original_claim
            numbers.insert(0, current.claim_number)
        return numbers


class ClaimReversalService:
    """Reverses a claim without erasing it."""

    @classmethod
    @transaction.atomic
    def reverse(cls, *, claim: PrescriptionClaim, actor, reason: str, adapter=None) -> ClaimReversal:
        """Record a reversal, notify the insurer, and clear the receivable.

        The original claim keeps its amounts and its adjudication. Medicine was
        supplied and a claim was made; if either was wrong, the truthful record
        is that it happened and was reversed, not that it never happened.
        """
        if not str(reason).strip():
            raise ValidationError("A reversal requires a reason.")
        if actor is None:
            raise PermissionDenied("A reversal requires a named actor.")

        already = ClaimReversal.all_objects.filter(
            tenant_id=claim.tenant_id, claim=claim, status="COMPLETED"
        ).first()
        if already is not None:
            raise ValidationError(
                f"This claim was already reversed by {already.reversal_number}."
            )

        reversal = ClaimReversal.all_objects.create(
            tenant_id=claim.tenant_id,
            claim=claim,
            reversal_number=f"REV-{claim.claim_number}-{secrets.token_hex(3)}",
            reason=reason,
            reversed_by=actor,
            status="COMPLETED",
        )

        if adapter is not None:
            adapter.reverse_claim(
                reference=claim.claim_number,
                reason=reason,
                idempotency_key=f"insurance:REVERSE:{claim.tenant_id}:{claim.pk}",
            )

        # The adjudication and the claimed amounts stay exactly as they were.
        # Only the forward-looking money changes: nothing further is owed.
        claim.adjudication_state = PrescriptionClaim.AdjudicationState.REVERSED
        claim.insurer_payable_amount = ZERO
        claim.save(
            update_fields=["adjudication_state", "insurer_payable_amount", "updated_at"]
        )
        return reversal

    @staticmethod
    def is_reversed(*, claim: PrescriptionClaim) -> bool:
        return ClaimReversal.all_objects.filter(
            tenant_id=claim.tenant_id, claim=claim, status="COMPLETED"
        ).exists()

    @staticmethod
    def recoverable_amount(*, claim: PrescriptionClaim) -> Decimal:
        """Money already received that must now be recovered.

        A reversal after payment does not cancel the payment -- the insurer has
        transferred funds, and getting them back is a separate act somebody has
        to perform.
        """
        return money(claim.paid_amount)
