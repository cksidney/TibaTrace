"""Preauthorisation, including partial approval.

The property that matters most here is that **a partial approval never silently
reduces a prescription**.

An insurer approving 30 of 60 tablets has made a funding decision, not a
clinical one. The prescription still says 60. What the patient does about the
other 30 -- pay cash, come back, have the prescriber appeal -- is a decision for
the patient and the pharmacist, and it can only be made if the shortfall is
visible. Quietly dispensing 30 and closing the episode hides a clinical fact
behind a billing outcome.

So line decisions are stored per line, and `supply_plan()` reports prescribed,
authorised and unfunded separately rather than returning one number.
"""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ..adapters.base import AdapterResult, BusinessState
from ..models import (
    PreauthorisationAttempt,
    PreauthorisationDecision,
    PreauthorisationLine,
    PrescriptionPreauthorisation,
)

ZERO = Decimal("0.00")
PENNY = Decimal("0.01")


def money(value) -> Decimal:
    if value is None:
        return ZERO
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


def quantity(value) -> Decimal:
    if value is None:
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


class PreauthorisationRequired(ValidationError):
    """Supply needs an authorisation that does not exist or is not valid."""


class PreauthorisationService:
    """Requests authorisation and records line-level decisions."""

    @staticmethod
    def build_idempotency_key(*, preauth: PrescriptionPreauthorisation) -> str:
        """Stable per preauthorisation.

        A duplicate request must not produce two unrelated authorisation
        numbers -- a pharmacy holding two for one prescription cannot tell which
        the insurer will honour.
        """
        return f"insurance:PREAUTH:{preauth.tenant_id}:{preauth.pk}"

    @staticmethod
    def is_required(*, insurer, scheme=None, amount: Decimal = ZERO, controlled: bool = False) -> bool:
        """Whether this supply needs authorisation before it happens.

        Deliberately conservative: where a threshold is not configured, a
        controlled medicine still requires authorisation. Guessing "no" commits
        the provider to money it may not recover.
        """
        threshold = getattr(scheme, "preauth_threshold_amount", None)
        if controlled:
            return True
        if threshold is None:
            return bool(getattr(insurer, "requires_preauthorisation", False))
        return money(amount) >= money(threshold)

    @classmethod
    def request(cls, *, preauth: PrescriptionPreauthorisation, adapter,
                lines: list[dict] | None = None) -> PreauthorisationAttempt:
        """Send the request and record the insurer's decision."""
        if preauth.status in {
            PrescriptionPreauthorisation.Status.APPROVED,
            PrescriptionPreauthorisation.Status.PARTIALLY_APPROVED,
        }:
            raise ValidationError(
                "This preauthorisation already carries a decision. "
                "Request a new one rather than overwriting it."
            )

        stored_lines = list(
            PreauthorisationLine.all_objects.filter(
                tenant_id=preauth.tenant_id, preauthorisation=preauth
            )
        )
        payload = {
            "preauth_number": preauth.preauth_number,
            "insurer": preauth.insurer.code,
            "lines": lines
            if lines is not None
            else [
                {
                    "line_reference": str(line.pk),
                    "quantity": str(line.requested_quantity),
                    "amount": "0.00",
                }
                for line in stored_lines
            ],
        }

        key = cls.build_idempotency_key(preauth=preauth)
        attempt_number = (
            PreauthorisationAttempt.all_objects.filter(
                tenant_id=preauth.tenant_id, preauthorisation=preauth
            ).count()
            + 1
        )

        result: AdapterResult = adapter.submit_preauthorisation(request=payload)

        attempt = PreauthorisationAttempt.all_objects.create(
            tenant_id=preauth.tenant_id,
            preauthorisation=preauth,
            attempt_number=attempt_number,
            idempotency_key=f"{key}:{attempt_number}",
            request_payload_digest=hashlib.sha256(
                json.dumps(payload, sort_keys=True, default=str).encode()
            ).hexdigest(),
            response_payload_digest=result.raw_response_digest,
            status="COMPLETED" if result.reached_insurer else "FAILED",
        )

        if result.reached_insurer:
            cls._apply_decision(preauth=preauth, result=result)
        return attempt

    @classmethod
    @transaction.atomic
    def _apply_decision(cls, *, preauth: PrescriptionPreauthorisation, result: AdapterResult) -> None:
        mapping = {
            BusinessState.APPROVED: PrescriptionPreauthorisation.Status.APPROVED,
            BusinessState.PARTIALLY_APPROVED: PrescriptionPreauthorisation.Status.PARTIALLY_APPROVED,
            BusinessState.REJECTED: PrescriptionPreauthorisation.Status.REJECTED,
            BusinessState.MORE_INFORMATION_REQUIRED: (
                PrescriptionPreauthorisation.Status.MORE_INFO_REQUIRED
            ),
            BusinessState.PENDING: PrescriptionPreauthorisation.Status.PENDING,
        }
        new_status = mapping.get(result.business_state)
        if new_status is None:
            return

        by_reference = {outcome.line_reference: outcome for outcome in result.lines}
        total_approved = ZERO

        for line in PreauthorisationLine.all_objects.filter(
            tenant_id=preauth.tenant_id, preauthorisation=preauth
        ):
            outcome = by_reference.get(str(line.pk))

            if outcome is None:
                # No line-level answer. A whole-request approval authorises the
                # requested quantity; anything else authorises nothing, because
                # silence is not permission.
                if new_status == PrescriptionPreauthorisation.Status.APPROVED:
                    line.approved_quantity = quantity(line.requested_quantity)
                    line.status = PreauthorisationLine.Status.APPROVED
                else:
                    line.approved_quantity = ZERO
                    line.status = PreauthorisationLine.Status.REJECTED
            else:
                approved = quantity(outcome.approved_quantity)
                requested = quantity(line.requested_quantity)
                # An insurer cannot authorise more than was asked for.
                line.approved_quantity = min(approved, requested)
                if line.approved_quantity <= ZERO:
                    line.status = PreauthorisationLine.Status.REJECTED
                elif line.approved_quantity < requested:
                    line.status = PreauthorisationLine.Status.PARTIALLY_APPROVED
                else:
                    line.status = PreauthorisationLine.Status.APPROVED
                line.rejection_reason = outcome.reason_description or outcome.reason_code

            line.save(
                update_fields=[
                    "approved_quantity", "status", "rejection_reason", "updated_at",
                ]
            )
            total_approved += money(getattr(outcome, "approved_amount", ZERO) if outcome else ZERO)

        preauth.status = new_status
        preauth.total_approved = money(total_approved)
        preauth.authorization_code = result.external_reference
        preauth.save(
            update_fields=["status", "total_approved", "authorization_code", "updated_at"]
        )

        PreauthorisationDecision.all_objects.create(
            tenant_id=preauth.tenant_id,
            preauthorisation=preauth,
            decision_code=result.business_state,
            decision_by=preauth.insurer.code,
            notes=result.response_message,
        )

    # ------------------------------------------------------------ supply plan

    @staticmethod
    def supply_plan(*, preauth: PrescriptionPreauthorisation) -> list[dict]:
        """Prescribed, authorised and unfunded, per line.

        Three numbers, never one. A partial approval is a funding decision, not
        a clinical one: the prescription still says what it said, and the
        shortfall has to be visible for the patient and pharmacist to decide
        what happens to it.
        """
        plan = []
        for line in PreauthorisationLine.all_objects.filter(
            tenant_id=preauth.tenant_id, preauthorisation=preauth
        ).select_related("sku"):
            prescribed = quantity(line.requested_quantity)
            authorised = quantity(line.approved_quantity)
            plan.append(
                {
                    "line_id": str(line.pk),
                    "sku_id": str(line.sku_id),
                    "prescribed_quantity": prescribed,
                    "authorised_quantity": authorised,
                    # What the patient must fund themselves, defer, or appeal.
                    "unfunded_quantity": max(ZERO, prescribed - authorised),
                    "status": line.status,
                    "reason": line.rejection_reason,
                }
            )
        return plan

    @staticmethod
    def is_valid_for_supply(*, preauth: PrescriptionPreauthorisation, on_date=None) -> bool:
        """Whether this authorisation may still be relied on.

        An expired authorisation is not an authorisation. Insurers refuse claims
        against them routinely, and the provider carries the cost.
        """
        if preauth.status not in {
            PrescriptionPreauthorisation.Status.APPROVED,
            PrescriptionPreauthorisation.Status.PARTIALLY_APPROVED,
        }:
            return False
        on_date = on_date or timezone.localdate()
        if preauth.valid_from and on_date < preauth.valid_from:
            return False
        if preauth.valid_to and on_date > preauth.valid_to:
            return False
        return True

    @classmethod
    def require_valid(cls, *, preauth: PrescriptionPreauthorisation | None, on_date=None):
        if preauth is None:
            raise PreauthorisationRequired(
                "This supply requires preauthorisation and none exists."
            )
        if not cls.is_valid_for_supply(preauth=preauth, on_date=on_date):
            raise PreauthorisationRequired(
                f"Preauthorisation {preauth.preauth_number} is {preauth.status} "
                "or outside its validity period, so it cannot fund this supply."
            )
        return preauth

    @staticmethod
    def invalidate_on_change(*, preauth: PrescriptionPreauthorisation, reason: str) -> None:
        """Void an authorisation whose basis changed.

        An authorisation is for specific medicines at specific quantities. Once
        those change it no longer describes what is being dispensed, and relying
        on it would mean claiming under an authorisation the insurer granted for
        something else.
        """
        preauth.status = PrescriptionPreauthorisation.Status.CANCELLED
        preauth.decision_notes = f"Invalidated: {reason}"
        preauth.save(update_fields=["status", "decision_notes", "updated_at"])

        PreauthorisationDecision.all_objects.create(
            tenant_id=preauth.tenant_id,
            preauthorisation=preauth,
            decision_code="INVALIDATED",
            decision_by="SYSTEM",
            notes=reason,
        )
