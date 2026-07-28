"""Services for the POS payment intent and settlement ledger.

All financial writes go through here. Serializers and views must never mutate
intent, tender, settlement or episode payment state directly.

The single most important function in this module is
``PaymentStateProjectionService.project``: ``DispensingEpisode.payment_state`` is
*derived* from the ledger, never set by a client. Everything else exists to
produce correct ledger facts for it to read.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.prescription.models import DispensingEpisode
from apps.prescription.payment_models import (
    PaymentIntent,
    PaymentReversal,
    PaymentSettlement,
    PaymentTender,
)
from apps.prescription.services.clinical_dispensing import _require_capability
from apps.workflows.service import emit_event

ZERO = Decimal("0")


def payload_hash(payload) -> str:
    """Stable hash of a provider payload, for duplicate detection and audit."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _emit(intent, event_type, payload):
    emit_event(
        tenant_id=str(intent.tenant_id),
        aggregate_type="PaymentIntent",
        aggregate_id=str(intent.id),
        event_type=event_type,
        payload={
            "branch_id": str(intent.branch_id),
            "episode_id": str(intent.dispensing_episode_id),
            "intent_id": str(intent.id),
            "correlation_id": str(intent.correlation_id),
            "device_id": intent.device_id,
            "register_id": intent.register_id,
            **payload,
        },
    )


class PaymentStateProjectionService:
    """Derives DispensingEpisode.payment_state from the payment ledger."""

    @staticmethod
    @transaction.atomic
    def project(*, intent):
        """Recompute intent totals and the episode's canonical payment state.

        Totals are recomputed from settlement and reversal rows rather than
        incremented in place, so a lost update cannot silently corrupt them.
        """
        intent = PaymentIntent.all_objects.select_for_update().get(pk=intent.pk)

        tenders = PaymentTender.all_objects.filter(payment_intent=intent)
        settled = (
            PaymentSettlement.all_objects.filter(payment_tender__in=tenders).aggregate(
                total=Sum("amount")
            )["total"]
            or ZERO
        )
        reversed_total = (
            PaymentReversal.all_objects.filter(
                settlement__payment_tender__in=tenders, status=PaymentReversal.Status.COMPLETED
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )
        pending_reversal = PaymentReversal.all_objects.filter(
            settlement__payment_tender__in=tenders,
            status__in=[PaymentReversal.Status.REQUESTED, PaymentReversal.Status.APPROVED],
        ).exists()

        intent.amount_settled = settled
        intent.amount_reversed = reversed_total
        effective = settled - reversed_total

        if intent.status == PaymentIntent.Status.CANCELLED:
            pass
        elif pending_reversal:
            intent.status = PaymentIntent.Status.REVERSAL_PENDING
        elif effective <= ZERO and reversed_total > ZERO:
            intent.status = PaymentIntent.Status.REVERSED
        elif effective >= intent.amount_due and intent.amount_due > ZERO:
            intent.status = PaymentIntent.Status.SETTLED
        elif effective > ZERO:
            intent.status = PaymentIntent.Status.PARTIALLY_SETTLED
        elif intent.amount_due == ZERO:
            intent.status = PaymentIntent.Status.SETTLED
        else:
            intent.status = PaymentIntent.Status.OPEN

        intent.version += 1
        intent.save(update_fields=["amount_settled", "amount_reversed", "status", "version"])

        episode_state = PaymentStateProjectionService._episode_state(intent, effective)
        episode = DispensingEpisode.all_objects.select_for_update().get(
            pk=intent.dispensing_episode_id
        )
        if episode.payment_state != episode_state:
            previous = episode.payment_state
            episode.payment_state = episode_state
            episode.save(update_fields=["payment_state"])
            _emit(
                intent,
                "DispensingPaymentStateProjected",
                {
                    "previous_state": previous,
                    "payment_state": episode_state,
                    "effective_settled": str(effective),
                    "amount_due": str(intent.amount_due),
                },
            )
        return intent

    @staticmethod
    def _episode_state(intent, effective):
        """Map ledger facts onto the canonical episode payment state."""
        if intent.status == PaymentIntent.Status.CANCELLED:
            return "CANCELLED"
        if intent.status == PaymentIntent.Status.REVERSAL_PENDING:
            return "REVERSAL_PENDING"
        if intent.status == PaymentIntent.Status.REVERSED:
            return "REVERSED"
        if intent.amount_due <= ZERO:
            return "NOT_REQUIRED"
        if effective >= intent.amount_due:
            return "PAID"
        if effective > ZERO:
            return "PARTIALLY_PAID"
        return "PENDING"


class PaymentIntentService:
    @staticmethod
    @transaction.atomic
    def create(
        *,
        episode,
        amount_due,
        actor,
        idempotency_key,
        currency="KES",
        device_id="",
        register_id="",
    ):
        _require_capability(actor, episode.tenant_id, "pos.payment.intent.create")
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})

        existing = PaymentIntent.all_objects.filter(
            tenant_id=episode.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            return existing

        amount_due = Decimal(str(amount_due))
        if amount_due < ZERO:
            raise ValidationError("Amount due cannot be negative.")

        active = PaymentIntent.all_objects.filter(
            dispensing_episode=episode, status__in=PaymentIntent.ACTIVE_STATUSES
        ).first()
        if active:
            raise ValidationError(
                f"Episode already has an active payment intent ({active.status})."
            )

        intent = PaymentIntent.all_objects.create(
            tenant_id=episode.tenant_id,
            branch=episode.branch,
            dispensing_episode=episode,
            device_id=device_id,
            register_id=register_id,
            currency=currency,
            amount_due=amount_due,
            status=PaymentIntent.Status.OPEN,
            idempotency_key=idempotency_key,
            created_by=actor,
        )
        _emit(intent, "PaymentIntentCreated", {"amount_due": str(amount_due), "currency": currency})
        PaymentStateProjectionService.project(intent=intent)
        intent.refresh_from_db()
        return intent

    @staticmethod
    @transaction.atomic
    def cancel(*, intent, actor, reason=""):
        _require_capability(actor, intent.tenant_id, "pos.payment.cancel")
        intent = PaymentIntent.all_objects.select_for_update().get(pk=intent.pk)
        if intent.effective_settled > ZERO:
            raise ValidationError(
                "Cannot cancel an intent that already holds settled value; reverse it instead."
            )
        intent.status = PaymentIntent.Status.CANCELLED
        intent.save(update_fields=["status"])
        PaymentTender.all_objects.filter(
            payment_intent=intent, status__in=[PaymentTender.Status.ALLOCATED, PaymentTender.Status.PENDING]
        ).update(status=PaymentTender.Status.CANCELLED)
        _emit(intent, "PaymentIntentCancelled", {"reason": reason})
        PaymentStateProjectionService.project(intent=intent)
        return intent


class PaymentTenderService:
    @staticmethod
    @transaction.atomic
    def allocate(
        *,
        intent,
        tender_type,
        allocated_amount,
        actor,
        idempotency_key,
        provider="MANUAL",
        register_id="",
        shift=None,
        register_session=None,
        operator_shift=None,
    ):
        """Allocate part of the intent to a payment method."""
        _require_capability(actor, intent.tenant_id, "pos.payment.tender.allocate")
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})

        existing = PaymentTender.all_objects.filter(
            tenant_id=intent.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            return existing

        intent = PaymentIntent.all_objects.select_for_update().get(pk=intent.pk)
        if intent.status not in PaymentIntent.ACTIVE_STATUSES:
            raise ValidationError(f"Payment intent is {intent.status}; cannot allocate a tender.")

        amount = Decimal(str(allocated_amount))
        if amount <= ZERO:
            raise ValidationError("Tender allocation must be greater than zero.")

        # Allocations across live tenders may not exceed what is owed. Without
        # this, a split tender could be over-allocated and over-collected.
        live = PaymentTender.all_objects.filter(
            payment_intent=intent, status__in=PaymentTender.LIVE_STATUSES
        ).aggregate(total=Sum("allocated_amount"))["total"] or ZERO
        if live + amount > intent.amount_due:
            raise ValidationError(
                f"Allocating {amount} would exceed the amount due "
                f"({live} of {intent.amount_due} already allocated)."
            )

        tender = PaymentTender.all_objects.create(
            tenant_id=intent.tenant_id,
            payment_intent=intent,
            tender_type=tender_type,
            provider=provider,
            register_session=register_session,
            operator_shift=operator_shift,
            allocated_amount=amount,
            register_id=register_id,
            shift=shift,
            idempotency_key=idempotency_key,
            created_by=actor,
        )
        _emit(
            intent,
            "PaymentTenderAllocated",
            {"tender_id": str(tender.id), "tender_type": tender_type, "amount": str(amount)},
        )
        return tender

    @staticmethod
    @transaction.atomic
    def cancel(*, tender, actor, reason=""):
        _require_capability(actor, tender.tenant_id, "pos.payment.cancel")
        tender = PaymentTender.all_objects.select_for_update().get(pk=tender.pk)
        if tender.effective_settled > ZERO:
            raise ValidationError("Cannot cancel a tender holding settled value; reverse it first.")
        tender.status = PaymentTender.Status.CANCELLED
        tender.save(update_fields=["status"])
        _emit(
            tender.payment_intent,
            "PaymentTenderCancelled",
            {"tender_id": str(tender.id), "reason": reason},
        )
        PaymentStateProjectionService.project(intent=tender.payment_intent)
        return tender


class PaymentSettlementService:
    """Records the immutable fact that value was received."""

    @staticmethod
    @transaction.atomic
    def record(
        *,
        tender,
        amount,
        source,
        idempotency_key,
        actor=None,
        attempt=None,
        provider_reference="",
        settlement_reference="",
        settled_at=None,
        hash_of_payload="",
    ):
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})

        # Replay returns the original fact rather than creating a second one.
        existing = PaymentSettlement.all_objects.filter(
            tenant_id=tender.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            return existing

        tender = PaymentTender.all_objects.select_for_update().get(pk=tender.pk)
        intent = PaymentIntent.all_objects.select_for_update().get(pk=tender.payment_intent_id)

        amount = Decimal(str(amount))
        if amount <= ZERO:
            raise ValidationError("Settlement amount must be greater than zero.")
        if tender.status in [PaymentTender.Status.CANCELLED, PaymentTender.Status.REVERSED]:
            raise ValidationError(f"Tender is {tender.status}; it cannot be settled.")

        already = PaymentSettlement.all_objects.filter(payment_tender=tender).aggregate(
            total=Sum("amount")
        )["total"] or ZERO
        if already + amount > tender.allocated_amount:
            raise ValidationError(
                f"Settling {amount} would exceed the tender allocation "
                f"({already} of {tender.allocated_amount} already settled)."
            )

        settlement = PaymentSettlement.all_objects.create(
            tenant_id=tender.tenant_id,
            payment_tender=tender,
            payment_attempt=attempt,
            amount=amount,
            currency=intent.currency,
            provider_reference=provider_reference,
            settlement_reference=settlement_reference,
            source=source,
            settled_at=settled_at or timezone.now(),
            idempotency_key=idempotency_key,
            payload_hash=hash_of_payload,
            recorded_by=actor,
        )

        total_settled = already + amount
        tender.settled_amount = total_settled
        tender.status = (
            PaymentTender.Status.SETTLED
            if total_settled >= tender.allocated_amount
            else PaymentTender.Status.PARTIALLY_SETTLED
        )
        if provider_reference and not tender.external_reference:
            tender.external_reference = provider_reference
        tender.save(update_fields=["settled_amount", "status", "external_reference"])

        _emit(
            intent,
            "PaymentSettlementRecorded",
            {
                "tender_id": str(tender.id),
                "settlement_id": str(settlement.id),
                "amount": str(amount),
                "source": source,
                "provider_reference": provider_reference,
            },
        )
        PaymentStateProjectionService.project(intent=intent)
        return settlement

    @staticmethod
    @transaction.atomic
    def settle_cash(
        *, tender, cash_received, actor, idempotency_key, shift=None, register_id=""
    ):
        """Cash at the till. Change is computed once, here, and stored."""
        _require_capability(actor, tender.tenant_id, "pos.payment.cash.accept")
        if tender.tender_type != "CASH":
            raise ValidationError("settle_cash requires a CASH tender.")

        cash_received = Decimal(str(cash_received))
        if cash_received < tender.allocated_amount:
            raise ValidationError(
                f"Cash received ({cash_received}) is less than the allocated amount "
                f"({tender.allocated_amount})."
            )

        settlement = PaymentSettlementService.record(
            tender=tender,
            amount=tender.allocated_amount,
            source=PaymentSettlement.Source.CASH,
            idempotency_key=idempotency_key,
            actor=actor,
        )
        # record() may have returned an existing settlement on replay; only
        # stamp cash bookkeeping the first time.
        tender.refresh_from_db()
        if tender.cash_received is None:
            tender.cash_received = cash_received
            tender.change_due = cash_received - tender.allocated_amount
            if shift is not None:
                tender.shift = shift
            if register_id:
                tender.register_id = register_id
            tender.save(update_fields=["cash_received", "change_due", "shift", "register_id"])
        return settlement

    @staticmethod
    @transaction.atomic
    def confirm_card(*, tender, approval_reference, approved_amount, actor, idempotency_key):
        """Record a card approval that a person read off a terminal.

        This is manual confirmation, not an integrated card-terminal flow: the
        approval reference is keyed in by the cashier and is trusted as typed.
        """
        _require_capability(actor, tender.tenant_id, "pos.payment.card.confirm")
        if tender.tender_type != "CARD":
            raise ValidationError("confirm_card requires a CARD tender.")
        if not approval_reference:
            raise ValidationError("A card approval reference is required.")

        return PaymentSettlementService.record(
            tender=tender,
            amount=approved_amount,
            source=PaymentSettlement.Source.CARD_MANUAL,
            idempotency_key=idempotency_key,
            actor=actor,
            provider_reference=approval_reference,
        )


class PaymentReversalService:
    @staticmethod
    @transaction.atomic
    def request(*, settlement, amount, reason, actor, idempotency_key):
        _require_capability(actor, settlement.tenant_id, "pos.payment.reverse")
        if not reason:
            raise ValidationError("A reversal reason is required.")

        existing = PaymentReversal.all_objects.filter(
            tenant_id=settlement.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            return existing

        amount = Decimal(str(amount))
        already = PaymentReversal.all_objects.filter(
            settlement=settlement,
            status__in=[
                PaymentReversal.Status.REQUESTED,
                PaymentReversal.Status.APPROVED,
                PaymentReversal.Status.COMPLETED,
            ],
        ).aggregate(total=Sum("amount"))["total"] or ZERO
        if already + amount > settlement.amount:
            raise ValidationError(
                f"Reversing {amount} would exceed the settled amount ({settlement.amount})."
            )

        reversal = PaymentReversal.all_objects.create(
            tenant_id=settlement.tenant_id,
            settlement=settlement,
            amount=amount,
            reason=reason,
            status=PaymentReversal.Status.REQUESTED,
            requested_by=actor,
            idempotency_key=idempotency_key,
        )
        intent = settlement.payment_tender.payment_intent
        _emit(
            intent,
            "PaymentReversalRequested",
            {"settlement_id": str(settlement.id), "reversal_id": str(reversal.id), "amount": str(amount)},
        )
        PaymentStateProjectionService.project(intent=intent)
        return reversal

    @staticmethod
    @transaction.atomic
    def complete(*, reversal, actor):
        """Approve and complete a reversal.

        Separation of duties: the approver must differ from the requester, so a
        single cashier cannot both take money back and sign it off.
        """
        _require_capability(actor, reversal.tenant_id, "pos.payment.reverse")
        reversal = PaymentReversal.all_objects.select_for_update().get(pk=reversal.pk)
        if reversal.status == PaymentReversal.Status.COMPLETED:
            return reversal
        if actor is not None and reversal.requested_by_id == actor.id:
            raise ValidationError(
                "A reversal must be approved by someone other than the requester."
            )

        reversal.approved_by = actor
        reversal.status = PaymentReversal.Status.COMPLETED
        reversal.completed_at = timezone.now()
        reversal.save(update_fields=["approved_by", "status", "completed_at"])

        tender = PaymentTender.all_objects.select_for_update().get(
            pk=reversal.settlement.payment_tender_id
        )
        tender.reversed_amount = PaymentReversal.all_objects.filter(
            settlement__payment_tender=tender, status=PaymentReversal.Status.COMPLETED
        ).aggregate(total=Sum("amount"))["total"] or ZERO
        if tender.reversed_amount >= tender.settled_amount:
            tender.status = PaymentTender.Status.REVERSED
        tender.save(update_fields=["reversed_amount", "status"])

        intent = tender.payment_intent
        _emit(
            intent,
            "PaymentReversalCompleted",
            {"reversal_id": str(reversal.id), "amount": str(reversal.amount)},
        )
        PaymentStateProjectionService.project(intent=intent)
        return reversal


def new_idempotency_key(prefix="pay"):
    """Convenience for callers that genuinely have no client-supplied key."""
    return f"{prefix}:{uuid.uuid4().hex}"
