"""Provider settlement and split-tender orchestration.

Sits between the provider adapters and the payment ledger. Its whole job is to
turn "a provider said something" into "a settlement fact exists", exactly once,
and to keep the intent's totals honest while several tenders settle
independently.

The recurring hazard here is double-counting. A provider may deliver the same
callback twice, deliver it before the initiation response has been persisted, or
deliver it long after a timeout was declared. Each of those must converge on one
settlement, never two.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.prescription.payment_models import (
    PaymentAttempt,
    PaymentIntent,
    PaymentProviderEvent,
    PaymentSettlement,
    PaymentTender,
)
from apps.prescription.payment_providers import ProviderEvent, get_adapter
from apps.prescription.payment_services import (
    PaymentSettlementService,
    PaymentStateProjectionService,
    payload_hash,
)
from apps.prescription.services.clinical_dispensing import _require_capability

ZERO = Decimal("0")

#: How far a provider-reported amount may differ from what was requested before
#: the settlement is refused. Zero: a payment for the wrong amount is a
#: reconciliation problem for a human, not something to absorb silently.
AMOUNT_TOLERANCE = ZERO


class PaymentAttemptService:
    @staticmethod
    @transaction.atomic
    def initiate(*, tender, actor, provider_code="FAKE", context=None, adapter=None):
        """Ask a provider to collect. Records that we asked -- nothing more."""
        _require_capability(actor, tender.tenant_id, "pos.payment.provider.initiate")

        tender = PaymentTender.all_objects.select_for_update().get(pk=tender.pk)
        if tender.status in {PaymentTender.Status.SETTLED, PaymentTender.Status.CANCELLED}:
            raise ValidationError(f"Tender is {tender.status}; it cannot be initiated.")

        outstanding = tender.allocated_amount - tender.settled_amount
        if outstanding <= ZERO:
            raise ValidationError("Tender is already fully settled.")

        attempt_number = (
            PaymentAttempt.all_objects.filter(payment_tender=tender).count() + 1
        )
        # Generated before we call out, so a callback that arrives before the
        # initiation response can still be matched to this attempt.
        request_reference = f"REQ-{tender.pk.hex[:12]}-{attempt_number}"

        attempt = PaymentAttempt.all_objects.create(
            tenant_id=tender.tenant_id,
            payment_tender=tender,
            provider=provider_code,
            attempt_number=attempt_number,
            request_reference=request_reference,
            requested_amount=outstanding,
            status=PaymentAttempt.Status.STARTED,
            idempotency_key=f"attempt:{tender.pk}:{attempt_number}",
        )

        adapter = adapter or get_adapter(provider_code)
        result = adapter.initiate(attempt=attempt, context=context or {})

        attempt.provider_reference = result.provider_reference
        attempt.response_payload_hash = payload_hash(
            {"accepted": result.accepted, "status": result.provider_status}
        )
        if result.accepted:
            attempt.status = PaymentAttempt.Status.ACCEPTED
            tender.status = PaymentTender.Status.PENDING
            tender.save(update_fields=["status"])
        else:
            attempt.status = PaymentAttempt.Status.FAILED
            attempt.failure_code = result.failure_code
            attempt.failure_reason = result.failure_reason
            attempt.completed_at = timezone.now()
        attempt.save()
        return attempt, result


class PaymentEventService:
    @staticmethod
    @transaction.atomic
    def apply(*, tenant, provider_code, event: ProviderEvent, raw_payload=None, authenticated=True):
        """Apply a provider event, exactly once.

        Returns (PaymentProviderEvent, PaymentSettlement | None). A duplicate,
        unauthenticated or unmatched event is recorded and then ignored -- it
        must leave a trace without moving money.
        """
        raw_payload = raw_payload or {}

        if not authenticated:
            # Recorded so a forged or misdirected delivery is visible, but never
            # applied: an event we cannot authenticate could mint a settlement.
            return (
                PaymentProviderEvent.all_objects.create(
                    tenant=tenant,
                    provider=provider_code,
                    event_type=event.event_type,
                    event_id=event.event_id,
                    provider_reference=event.provider_reference,
                    request_reference=event.request_reference,
                    payload_hash=payload_hash(raw_payload),
                    authenticated=False,
                    processing_status=PaymentProviderEvent.ProcessingStatus.REJECTED,
                    processing_error="Event failed authentication.",
                ),
                None,
            )

        # Duplicate delivery is normal provider behaviour, not an error.
        if event.event_id:
            existing = PaymentProviderEvent.all_objects.filter(
                tenant=tenant, provider=provider_code, event_id=event.event_id
            ).first()
            if existing:
                duplicate = PaymentProviderEvent.all_objects.create(
                    tenant=tenant,
                    provider=provider_code,
                    event_type=event.event_type,
                    event_id="",  # the unique constraint is on the first arrival
                    provider_reference=event.provider_reference,
                    request_reference=event.request_reference,
                    payload_hash=payload_hash(raw_payload),
                    authenticated=True,
                    processing_status=PaymentProviderEvent.ProcessingStatus.DUPLICATE,
                    processing_error=f"Duplicate of event {event.event_id}.",
                )
                return duplicate, None

        record = PaymentProviderEvent.all_objects.create(
            tenant=tenant,
            provider=provider_code,
            event_type=event.event_type,
            event_id=event.event_id,
            provider_reference=event.provider_reference,
            request_reference=event.request_reference,
            payload_hash=payload_hash(raw_payload),
            authenticated=True,
            processing_status=PaymentProviderEvent.ProcessingStatus.AUTHENTICATED,
        )

        attempt = PaymentAttempt.all_objects.filter(
            tenant=tenant, request_reference=event.request_reference
        ).first()
        if attempt is None:
            # Callback-before-initiation-response, or an event for a request we
            # never made. Held as unmatched for reconciliation rather than
            # discarded, so a real payment is not lost.
            record.processing_status = PaymentProviderEvent.ProcessingStatus.UNMATCHED
            record.processing_error = "No attempt matches this request reference."
            record.save(update_fields=["processing_status", "processing_error"])
            return record, None

        if event.status != "SUCCEEDED":
            attempt.status = (
                PaymentAttempt.Status.FAILED
                if event.status == "FAILED"
                else PaymentAttempt.Status.STARTED
            )
            attempt.completed_at = timezone.now() if event.status == "FAILED" else None
            attempt.save(update_fields=["status", "completed_at"])
            record.processing_status = PaymentProviderEvent.ProcessingStatus.PROCESSED
            record.save(update_fields=["processing_status"])
            return record, None

        # A success for the wrong amount is not settled silently. Absorbing it
        # would leave the ledger disagreeing with the provider.
        if event.amount is None or abs(event.amount - attempt.requested_amount) > AMOUNT_TOLERANCE:
            record.processing_status = PaymentProviderEvent.ProcessingStatus.REJECTED
            record.processing_error = (
                f"Amount mismatch: provider reported {event.amount}, "
                f"attempt requested {attempt.requested_amount}."
            )
            record.save(update_fields=["processing_status", "processing_error"])
            return record, None

        settlement = PaymentSettlementService.record(
            tender=attempt.payment_tender,
            amount=event.amount,
            source=PaymentSettlement.Source.PROVIDER_EVENT,
            # Keyed on the provider's own event id, so a redelivery that somehow
            # reaches here still collapses onto one settlement.
            idempotency_key=f"provider-event:{provider_code}:{event.event_id or event.provider_reference}",
            attempt=attempt,
            provider_reference=event.provider_reference,
            hash_of_payload=payload_hash(raw_payload),
        )

        attempt.status = PaymentAttempt.Status.SUCCEEDED
        attempt.completed_at = timezone.now()
        attempt.save(update_fields=["status", "completed_at"])

        record.processing_status = PaymentProviderEvent.ProcessingStatus.PROCESSED
        record.save(update_fields=["processing_status"])
        return record, settlement


class SplitTenderService:
    """Allocation across several tenders for one intent."""

    @staticmethod
    def summary(*, intent):
        """Totals the till needs to show, computed from the ledger."""
        tenders = list(PaymentTender.all_objects.filter(payment_intent=intent))
        live = [t for t in tenders if t.status in PaymentTender.LIVE_STATUSES]
        allocated = sum((t.allocated_amount for t in live), ZERO)
        settled = sum((t.effective_settled for t in live), ZERO)
        pending = sum(
            (t.allocated_amount - t.effective_settled for t in live if t.status == PaymentTender.Status.PENDING),
            ZERO,
        )
        failed = sum(
            (t.allocated_amount for t in tenders if t.status == PaymentTender.Status.FAILED),
            ZERO,
        )
        return {
            "amount_due": intent.amount_due,
            "allocated": allocated,
            "settled": settled,
            "pending": pending,
            "failed": failed,
            "unallocated": max(ZERO, intent.amount_due - allocated),
            "remaining": max(ZERO, intent.amount_due - settled),
            "fully_allocated": allocated >= intent.amount_due,
            "fully_settled": settled >= intent.amount_due and intent.amount_due > ZERO,
        }

    @staticmethod
    @transaction.atomic
    def replace_failed_tender(*, tender, actor, tender_type, idempotency_key, provider="MANUAL"):
        """Cancel a failed tender and allocate its amount to a replacement.

        A failed component must not strand the money already collected on other
        tenders, and must not silently leave the intent under-allocated.
        """
        from apps.prescription.payment_services import PaymentTenderService

        tender = PaymentTender.all_objects.select_for_update().get(pk=tender.pk)
        if tender.effective_settled > ZERO:
            raise ValidationError(
                "This tender holds settled value; reverse it rather than replacing it."
            )
        amount = tender.allocated_amount
        PaymentTenderService.cancel(tender=tender, actor=actor, reason="Replaced after failure")
        return PaymentTenderService.allocate(
            intent=tender.payment_intent,
            tender_type=tender_type,
            allocated_amount=amount,
            actor=actor,
            idempotency_key=idempotency_key,
            provider=provider,
        )

    @staticmethod
    @transaction.atomic
    def finalise(*, intent):
        """Recompute totals and project the episode's payment state.

        Locks the intent first: two terminals settling the last two tenders at
        once must not both read a stale total and each conclude the balance is
        still outstanding.
        """
        intent = PaymentIntent.all_objects.select_for_update().get(pk=intent.pk)
        PaymentStateProjectionService.project(intent=intent)
        intent.refresh_from_db()
        return SplitTenderService.summary(intent=intent)


def new_request_reference(prefix="REQ"):
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def settled_total(intent) -> Decimal:
    """Effective settled value for an intent, straight from settlement rows."""
    tenders = PaymentTender.all_objects.filter(payment_intent=intent)
    return (
        PaymentSettlement.all_objects.filter(payment_tender__in=tenders).aggregate(
            total=Sum("amount")
        )["total"]
        or ZERO
    )
