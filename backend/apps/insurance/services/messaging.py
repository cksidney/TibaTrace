"""Outbox dispatch and inbound callback handling.

Two problems, one shape.

**Outbound.** A claim state change and the decision to tell the insurer must
commit together. If the state is written and the send is not, the claim sits
READY_TO_SUBMIT forever and somebody eventually resubmits by hand. If the send
happens and the state write rolls back, the insurer holds a claim we have no
record of sending -- and the next submission is a duplicate. So the outbox row
is written inside the same transaction as the state change, and dispatch happens
afterwards by reading that row.

**Inbound.** An insurer callback is an unauthenticated HTTP request until proven
otherwise. Knowing a claim reference proves nothing: references appear on
remittance advices, in emails, and in any breach of the insurer's own systems. A
callback is therefore verified before it is read, deduplicated before it is
applied, and correlated to a tenant before it can touch anything.

Neither direction assumes delivery is exactly once. Retries are expected, so
every path is idempotent and a replay is a no-op rather than a second claim or a
second payment.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from ..models import InsuranceInboxMessage, InsuranceOutboxMessage

ZERO = Decimal("0.00")

#: How long a signed callback stays acceptable. A captured request replayed
#: weeks later must not still be valid.
CALLBACK_TOLERANCE = timedelta(minutes=5)

#: Bounded, so a permanently failing message stops consuming the queue instead
#: of being retried until somebody notices the log volume.
MAX_DISPATCH_ATTEMPTS = 5

#: Callback bodies are read into memory before verification, so the size cap is
#: applied first.
MAX_CALLBACK_BYTES = 256 * 1024


class OutboxExhausted(ValidationError):
    """The message has failed too many times to keep retrying."""


class CallbackRejected(PermissionDenied):
    """The callback could not be trusted, so nothing was changed."""


def canonical_digest(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class OutboxService:
    """Durable hand-off between a state change and an external call."""

    @staticmethod
    def enqueue(*, tenant_id, event_type: str, idempotency_key: str, payload: dict) -> InsuranceOutboxMessage:
        """Record an intent to call an insurer.

        Must be called inside the transaction that changes the claim, so the two
        commit or roll back together.
        """
        message, _ = InsuranceOutboxMessage.all_objects.get_or_create(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            defaults={"event_type": event_type, "payload": payload, "status": "PENDING"},
        )
        return message

    @staticmethod
    def claim_batch(*, tenant_id=None, limit: int = 50):
        """Take a batch of pending messages for dispatch.

        Rows are locked and marked IN_FLIGHT in one transaction so two workers
        cannot pick up the same message and call the insurer twice. The
        insurer-side idempotency key would make that harmless, but only for
        insurers that honour it.
        """
        with transaction.atomic():
            query = InsuranceOutboxMessage.all_objects.select_for_update(skip_locked=True).filter(
                status="PENDING"
            )
            if tenant_id is not None:
                query = query.filter(tenant_id=tenant_id)

            batch = list(query.order_by("created_at")[:limit])
            if batch:
                InsuranceOutboxMessage.all_objects.filter(
                    pk__in=[message.pk for message in batch]
                ).update(status="IN_FLIGHT", updated_at=timezone.now())
            return batch

    @staticmethod
    def mark_sent(*, message: InsuranceOutboxMessage) -> None:
        message.status = "SENT"
        message.save(update_fields=["status", "updated_at"])

    @staticmethod
    def mark_failed(*, message: InsuranceOutboxMessage, retryable: bool = True) -> None:
        """Return a message to the queue, or park it.

        A non-retryable failure is parked rather than retried: sending the same
        malformed payload again produces the same refusal and hides the real
        one behind noise.
        """
        message.retry_count += 1

        if not retryable:
            message.status = "FAILED"
        elif message.retry_count >= MAX_DISPATCH_ATTEMPTS:
            # Parked for a human, not silently dropped. The claim still needs
            # submitting, and somebody has to know it did not go.
            message.status = "EXHAUSTED"
        else:
            message.status = "PENDING"

        message.save(update_fields=["status", "retry_count", "updated_at"])

    @staticmethod
    def pending_count(*, tenant_id=None) -> int:
        query = InsuranceOutboxMessage.all_objects.filter(status__in=["PENDING", "IN_FLIGHT"])
        if tenant_id is not None:
            query = query.filter(tenant_id=tenant_id)
        return query.count()

    @staticmethod
    def stuck(*, older_than: timedelta = timedelta(minutes=30)):
        """Messages taken for dispatch and never resolved.

        A worker killed mid-dispatch leaves its batch IN_FLIGHT forever. These
        must surface, because each one is a claim the insurer has not been told
        about.
        """
        cutoff = timezone.now() - older_than
        return InsuranceOutboxMessage.all_objects.filter(
            status="IN_FLIGHT", updated_at__lt=cutoff
        )


class InboxService:
    """Verifies, deduplicates and records insurer callbacks."""

    @staticmethod
    def verify_signature(*, secret: str, body: bytes, signature: str, timestamp: str) -> bool:
        """Check an HMAC over timestamp and body.

        The timestamp is inside the signed material, so it cannot be edited to
        extend the validity of a captured request. Comparison is constant-time:
        a byte-by-byte comparison leaks how much of a forged signature was
        correct, which is enough to construct one.
        """
        if not secret or not signature or not timestamp:
            return False

        try:
            sent_at = float(timestamp)
        except (TypeError, ValueError):
            return False

        age = abs(timezone.now().timestamp() - sent_at)
        if age > CALLBACK_TOLERANCE.total_seconds():
            return False

        expected = hmac.new(
            secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @classmethod
    def accept(cls, *, tenant_id, insurer, body: bytes, headers: dict, secret: str) -> InsuranceInboxMessage:
        """Admit a callback, or refuse it without changing anything.

        Order matters and is deliberate: size, then signature, then parse, then
        deduplicate. Parsing before verifying would run a JSON decoder over
        unauthenticated input, and a claim reference inside an unverified body
        is not a reason to trust the body.
        """
        if len(body) > MAX_CALLBACK_BYTES:
            raise CallbackRejected("Callback payload exceeds the permitted size.")

        if not cls.verify_signature(
            secret=secret,
            body=body,
            signature=str(headers.get("X-Signature", "")),
            timestamp=str(headers.get("X-Timestamp", "")),
        ):
            raise CallbackRejected(
                "Callback signature is missing, invalid or outside the permitted time window."
            )

        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CallbackRejected("Callback body could not be parsed.") from exc

        event_id = str(payload.get("event_id") or "").strip()
        if not event_id:
            # Without an id there is no way to tell a retry from a new event,
            # so the insurer must supply one.
            raise CallbackRejected("Callback carries no event identifier.")

        existing = InsuranceInboxMessage.all_objects.filter(
            external_event_id=event_id
        ).first()
        if existing is not None:
            # A duplicate delivery is normal and must be a no-op. Returning the
            # original row lets the caller respond 200 without reprocessing.
            return existing

        return InsuranceInboxMessage.all_objects.create(
            tenant_id=tenant_id,
            source_insurer=insurer,
            external_event_id=event_id,
            payload_digest=canonical_digest(payload),
            processing_status="RECEIVED",
        )

    @staticmethod
    def mark_processed(*, message: InsuranceInboxMessage) -> None:
        message.processing_status = "PROCESSED"
        message.save(update_fields=["processing_status", "updated_at"])

    @staticmethod
    def mark_failed(*, message: InsuranceInboxMessage) -> None:
        message.processing_status = "FAILED"
        message.save(update_fields=["processing_status", "updated_at"])

    @staticmethod
    def is_duplicate(*, event_id: str) -> bool:
        return InsuranceInboxMessage.all_objects.filter(
            external_event_id=str(event_id)
        ).exists()
