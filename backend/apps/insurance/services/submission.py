"""Claim submission and adjudication.

The distinction the whole module protects: **transport acceptance is not
adjudication, and adjudication is not payment.**

An insurer returning HTTP 200 has received bytes. That is all. It has not
agreed the claim is valid, has not approved an amount, and has certainly not
paid. Each of those is a separate fact arriving at a separate time, and the
claim carries them in separate columns so no single value can be read as all
three.

The failure this prevents is a provider booking a receivable on transport
acceptance, reporting revenue that no insurer ever agreed to, and discovering
months later that the claims were rejected on arrival.
"""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from ..adapters.base import AdapterResult, BusinessState, TransportState
from ..models import (
    ClaimAdjudication,
    ClaimAdjudicationLine,
    ClaimSubmissionAttempt,
    InsuranceOutboxMessage,
    PrescriptionClaim,
    PrescriptionClaimLine,
)
from .claim_construction import ClaimConstructionService, money

ZERO = Decimal("0.00")


class ClaimNotSubmittable(ValidationError):
    """Validation failed, or the claim is in a state that forbids submission."""


def build_idempotency_key(*, claim: PrescriptionClaim, attempt_kind: str = "SUBMIT") -> str:
    """Stable across retries of the same submission.

    Derived from the claim and the kind of operation, never from a timestamp or
    a random value -- both would make a network retry look like a new claim to
    the insurer and create a duplicate.
    """
    return f"insurance:{attempt_kind}:{claim.tenant_id}:{claim.pk}"


def payload_digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ClaimSubmissionService:
    """Freezes a claim, hands it to an adapter, and records what came back."""

    @staticmethod
    def build_payload(*, claim: PrescriptionClaim) -> dict:
        """The provider-neutral submission payload.

        Adapters translate this into their insurer's format. Nothing
        insurer-specific belongs here.
        """
        lines = PrescriptionClaimLine.all_objects.filter(tenant_id=claim.tenant_id, claim=claim)
        return {
            "claim_number": claim.claim_number,
            "member_number": claim.member.membership_number,
            "scheme_code": claim.scheme.code,
            "currency": claim.currency,
            "gross_amount": str(money(claim.claimed_gross_amount)),
            "preauthorisation_reference": (
                getattr(claim.preauthorisation, "authorisation_number", "") or ""
            ),
            "lines": [
                {
                    "line_reference": str(line.pk),
                    "item_code": line.insurer_item_code,
                    "quantity": str(line.quantity),
                    "unit_price": str(money(line.unit_price)),
                    "amount": str(money(line.claimed_amount)),
                }
                for line in lines
            ],
        }

    @classmethod
    @transaction.atomic
    def prepare(cls, *, claim: PrescriptionClaim) -> dict:
        """Validate and freeze the claim for dispatch.

        Writes an outbox row in the same transaction as the state change, so a
        claim can never be marked ready without something existing to send it,
        and can never be sent without the claim recording that it was.
        """
        problems = ClaimConstructionService.validate_for_submission(claim=claim)
        if problems:
            claim.submission_state = PrescriptionClaim.SubmissionState.VALIDATION_FAILED
            claim.save(update_fields=["submission_state", "updated_at"])
            raise ClaimNotSubmittable({"claim": [p["message"] for p in problems]})

        payload = cls.build_payload(claim=claim)
        claim.submission_state = PrescriptionClaim.SubmissionState.READY_TO_SUBMIT
        claim.save(update_fields=["submission_state", "updated_at"])

        InsuranceOutboxMessage.all_objects.create(
            tenant_id=claim.tenant_id,
            event_type="ClaimSubmissionRequested",
            idempotency_key=f"outbox:submit:{claim.tenant_id}:{claim.pk}",
            payload={"claim_id": str(claim.pk), "digest": payload_digest(payload)},
            status="PENDING",
        )
        return payload

    @classmethod
    def submit(cls, *, claim: PrescriptionClaim, adapter, payload: dict | None = None) -> ClaimSubmissionAttempt:
        """Dispatch to the insurer and record the outcome.

        Deliberately not inside `prepare`'s transaction. An external call held
        open inside a database transaction keeps a write lock for the length of
        someone else's network, and a rollback after the insurer has already
        accepted the claim loses the only record that we sent it.
        """
        if claim.submission_state not in {
            PrescriptionClaim.SubmissionState.READY_TO_SUBMIT,
            PrescriptionClaim.SubmissionState.SUBMITTED,
        }:
            raise ClaimNotSubmittable(
                f"A claim in {claim.submission_state} cannot be submitted."
            )

        payload = payload if payload is not None else cls.build_payload(claim=claim)
        key = build_idempotency_key(claim=claim)

        attempt_number = (
            ClaimSubmissionAttempt.all_objects.filter(
                tenant_id=claim.tenant_id, claim=claim
            ).count()
            + 1
        )

        # The key sent to the insurer is stable across retries -- that is what
        # makes a retry idempotent to them. The local row needs its own unique
        # value, so the attempt number is appended for storage only.
        result: AdapterResult = adapter.submit_claim(request=payload, idempotency_key=key)

        attempt = ClaimSubmissionAttempt.all_objects.create(
            tenant_id=claim.tenant_id,
            claim=claim,
            idempotency_key=f"{key}:{attempt_number}",
            attempt_number=attempt_number,
            payload_digest=payload_digest(payload),
            transport_status=result.transport_state,
            business_status=result.business_state,
            external_reference=result.external_reference,
            response_code=result.response_code,
            response_message=result.response_message,
            response_payload_digest=result.raw_response_digest,
            retryable=result.retryable,
        )

        cls._apply_transport(claim=claim, result=result)
        if result.reached_insurer:
            cls._apply_business(claim=claim, result=result)
        return attempt

    @staticmethod
    def _apply_transport(*, claim: PrescriptionClaim, result: AdapterResult) -> None:
        """Record only whether the message arrived."""
        if result.transport_state == TransportState.ACCEPTED:
            claim.submission_state = PrescriptionClaim.SubmissionState.TRANSPORT_ACCEPTED
        elif result.transport_state == TransportState.REJECTED:
            claim.submission_state = PrescriptionClaim.SubmissionState.TRANSPORT_REJECTED
        else:
            # Timeout, outage, unparseable. We do not know whether the insurer
            # has it, so the claim stays submitted and awaits a status check --
            # marking it rejected would invite a duplicate resubmission.
            claim.submission_state = PrescriptionClaim.SubmissionState.SUBMITTED
        claim.save(update_fields=["submission_state", "updated_at"])

    @staticmethod
    def _apply_business(*, claim: PrescriptionClaim, result: AdapterResult) -> None:
        """Record the insurer's decision, if it made one."""
        mapping = {
            BusinessState.APPROVED: PrescriptionClaim.AdjudicationState.APPROVED,
            BusinessState.PARTIALLY_APPROVED: PrescriptionClaim.AdjudicationState.PARTIALLY_APPROVED,
            BusinessState.REJECTED: PrescriptionClaim.AdjudicationState.REJECTED,
            BusinessState.MORE_INFORMATION_REQUIRED: PrescriptionClaim.AdjudicationState.MORE_INFO_REQUIRED,
            BusinessState.REVERSED: PrescriptionClaim.AdjudicationState.REVERSED,
        }
        # PENDING, UNKNOWN and DUPLICATE deliberately leave adjudication alone.
        # None of them is a decision.
        new_state = mapping.get(result.business_state)
        if new_state is None:
            return

        claim.adjudication_state = new_state
        # Only an approval creates an insurer payable. Transport acceptance
        # never does, and neither does silence.
        if result.establishes_liability:
            claim.approved_amount = money(result.approved_amount or ZERO)
            claim.insurer_payable_amount = money(result.approved_amount or ZERO)
        else:
            claim.approved_amount = ZERO
            claim.insurer_payable_amount = ZERO
        claim.save(
            update_fields=[
                "adjudication_state", "approved_amount",
                "insurer_payable_amount", "updated_at",
            ]
        )


class ClaimAdjudicationService:
    """Records a formal adjudication, header and lines."""

    @classmethod
    @transaction.atomic
    def record(cls, *, claim: PrescriptionClaim, result: AdapterResult) -> ClaimAdjudication:
        if not result.reached_insurer:
            raise ValidationError(
                "An adjudication cannot be recorded from a response that never reached the insurer."
            )

        adjudication = ClaimAdjudication.all_objects.create(
            tenant_id=claim.tenant_id,
            claim=claim,
            adjudication_number=f"ADJ-{claim.claim_number}",
            status=result.business_state,
            approved_amount=money(result.approved_amount or ZERO),
            # Only an approval creates a liability. Anything else is zero,
            # whatever the insurer's transport said.
            insurer_liability=(
                money(result.approved_amount or ZERO) if result.establishes_liability else ZERO
            ),
        )

        for outcome in result.lines:
            line = PrescriptionClaimLine.all_objects.filter(
                tenant_id=claim.tenant_id, claim=claim, pk=outcome.line_reference
            ).first()
            if line is None:
                continue

            ClaimAdjudicationLine.all_objects.create(
                tenant_id=claim.tenant_id,
                adjudication=adjudication,
                claim_line=line,
                claimed_amount=money(outcome.claimed_amount),
                allowed_amount=money(outcome.allowed_amount),
                approved_amount=money(outcome.approved_amount),
                disallowed_amount=money(outcome.disallowed_amount),
                patient_liability=money(outcome.patient_liability),
                insurer_liability=money(outcome.approved_amount),
                reason_code=outcome.reason_code,
            )

            # The claimed amount is never overwritten. What we asked for and
            # what they allowed are both facts, and the difference is the
            # contractual adjustment somebody has to account for.
            line.approved_amount = money(outcome.approved_amount)
            line.disallowed_amount = money(outcome.disallowed_amount)
            line.status = outcome.status
            line.rejection_code = outcome.reason_code
            line.save(
                update_fields=[
                    "approved_amount", "disallowed_amount",
                    "status", "rejection_code", "updated_at",
                ]
            )

        return adjudication


def money_quantise(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
