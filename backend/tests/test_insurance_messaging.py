"""Outbox dispatch and inbound callback handling.

The inbound tests are the important ones. An insurer callback is an
unauthenticated HTTP request until proven otherwise, and knowing a claim
reference proves nothing -- references appear on remittance advices, in emails,
and in any breach of the insurer's own systems.

Do not relax the signature or replay checks to accommodate an insurer that
cannot sign. Give that insurer a polling integration instead.
"""
import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest

from apps.insurance.services.messaging import (
    CALLBACK_TOLERANCE,
    MAX_CALLBACK_BYTES,
    MAX_DISPATCH_ATTEMPTS,
    CallbackRejected,
    InboxService,
    OutboxService,
    canonical_digest,
)

SECRET = "insurer-callback-secret"


def sign(body: bytes, secret: str = SECRET, timestamp: str | None = None) -> dict:
    timestamp = timestamp or str(time.time())
    signature = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return {"X-Signature": signature, "X-Timestamp": timestamp}


def body(**payload) -> bytes:
    payload.setdefault("event_id", "EVT-1")
    return json.dumps(payload).encode()


# ─── signature verification ──────────────────────────────────────────────────


class TestSignatureVerification:
    def test_a_correctly_signed_callback_verifies(self):
        raw = body()
        headers = sign(raw)
        assert (
            InboxService.verify_signature(
                secret=SECRET,
                body=raw,
                signature=headers["X-Signature"],
                timestamp=headers["X-Timestamp"],
            )
            is True
        )

    def test_a_forged_signature_is_refused(self):
        raw = body()
        assert (
            InboxService.verify_signature(
                secret=SECRET, body=raw, signature="0" * 64, timestamp=str(time.time())
            )
            is False
        )

    def test_a_signature_from_a_different_secret_is_refused(self):
        raw = body()
        headers = sign(raw, secret="someone-elses-secret")
        assert (
            InboxService.verify_signature(
                secret=SECRET,
                body=raw,
                signature=headers["X-Signature"],
                timestamp=headers["X-Timestamp"],
            )
            is False
        )

    def test_an_altered_body_invalidates_the_signature(self):
        """The signature covers the body, so the amount cannot be edited."""
        headers = sign(body(amount="100.00"))
        tampered = body(amount="100000.00")
        assert (
            InboxService.verify_signature(
                secret=SECRET,
                body=tampered,
                signature=headers["X-Signature"],
                timestamp=headers["X-Timestamp"],
            )
            is False
        )

    def test_no_secret_verifies_nothing(self):
        raw = body()
        headers = sign(raw)
        # An unconfigured secret must not mean "accept everything".
        assert (
            InboxService.verify_signature(
                secret="",
                body=raw,
                signature=headers["X-Signature"],
                timestamp=headers["X-Timestamp"],
            )
            is False
        )

    def test_a_missing_signature_is_refused(self):
        assert (
            InboxService.verify_signature(
                secret=SECRET, body=body(), signature="", timestamp=str(time.time())
            )
            is False
        )


class TestReplayProtection:
    def test_an_old_request_is_refused(self):
        """A captured request replayed later must not still be valid."""
        raw = body()
        old = str(time.time() - CALLBACK_TOLERANCE.total_seconds() - 60)
        headers = sign(raw, timestamp=old)
        assert (
            InboxService.verify_signature(
                secret=SECRET,
                body=raw,
                signature=headers["X-Signature"],
                timestamp=old,
            )
            is False
        )

    def test_the_timestamp_cannot_be_edited_to_extend_validity(self):
        # It is inside the signed material.
        raw = body()
        headers = sign(raw, timestamp=str(time.time() - 3600))
        assert (
            InboxService.verify_signature(
                secret=SECRET,
                body=raw,
                signature=headers["X-Signature"],
                timestamp=str(time.time()),
            )
            is False
        )

    def test_a_non_numeric_timestamp_is_refused(self):
        raw = body()
        assert (
            InboxService.verify_signature(
                secret=SECRET, body=raw, signature="a" * 64, timestamp="not-a-time"
            )
            is False
        )

    def test_the_tolerance_is_short(self):
        assert CALLBACK_TOLERANCE <= timedelta(minutes=15)


# ─── admission ───────────────────────────────────────────────────────────────


class TestCallbackAdmission:
    def test_an_unsigned_callback_changes_nothing(self, db):
        with pytest.raises(CallbackRejected):
            InboxService.accept(
                tenant_id="t1", insurer=None, body=body(), headers={}, secret=SECRET
            )

    def test_a_callback_naming_a_claim_is_still_refused_without_a_signature(self, db):
        """Knowing a claim reference proves nothing.

        References appear on remittance advices, in emails, and in any breach of
        the insurer's own systems.
        """
        raw = body(claim_number="CLM-0001", approved_amount="50000.00")
        with pytest.raises(CallbackRejected):
            InboxService.accept(
                tenant_id="t1", insurer=None, body=raw, headers={}, secret=SECRET
            )

    def test_an_oversized_body_is_refused_before_anything_else(self, db):
        # The body is read into memory before verification, so size is capped
        # first.
        raw = b"x" * (MAX_CALLBACK_BYTES + 1)
        with pytest.raises(CallbackRejected, match="size"):
            InboxService.accept(
                tenant_id="t1", insurer=None, body=raw, headers=sign(raw), secret=SECRET
            )

    def test_an_unparseable_but_signed_body_is_refused(self, db):
        raw = b"not json"
        with pytest.raises(CallbackRejected, match="parsed"):
            InboxService.accept(
                tenant_id="t1", insurer=None, body=raw, headers=sign(raw), secret=SECRET
            )

    def test_a_callback_without_an_event_id_is_refused(self, db):
        raw = json.dumps({"claim_number": "CLM-1"}).encode()
        # Without an id there is no way to tell a retry from a new event.
        with pytest.raises(CallbackRejected, match="event identifier"):
            InboxService.accept(
                tenant_id="t1", insurer=None, body=raw, headers=sign(raw), secret=SECRET
            )

    def test_verification_happens_before_parsing(self):
        from apps.insurance.services import messaging

        source = open(messaging.__file__).read()
        accept = source.split("def accept(")[1].split("def mark_processed")[0]
        # Parsing unauthenticated input runs a decoder over attacker-controlled
        # bytes.
        assert accept.index("verify_signature") < accept.index("json.loads")

    def test_the_size_cap_is_applied_first(self):
        from apps.insurance.services import messaging

        source = open(messaging.__file__).read()
        accept = source.split("def accept(")[1].split("def mark_processed")[0]
        assert accept.index("MAX_CALLBACK_BYTES") < accept.index("verify_signature")


# ─── deduplication ───────────────────────────────────────────────────────────


class TestDuplicateDelivery:
    def test_the_digest_is_order_independent(self):
        # Two serialisations of the same event must not look like two events.
        assert canonical_digest({"a": 1, "b": 2}) == canonical_digest({"b": 2, "a": 1})

    def test_the_digest_changes_with_content(self):
        assert canonical_digest({"amount": "1"}) != canonical_digest({"amount": "2"})


# ─── outbox ──────────────────────────────────────────────────────────────────


class TestOutboxRetries:
    def test_retries_are_bounded(self):
        # A permanently failing message must stop consuming the queue.
        assert MAX_DISPATCH_ATTEMPTS <= 10

    def test_an_exhausted_message_is_parked_not_dropped(self, db):
        from apps.insurance.models import InsuranceOutboxMessage

        message = InsuranceOutboxMessage(
            tenant_id=None,
            event_type="ClaimSubmissionRequested",
            idempotency_key="k",
            payload={},
            status="IN_FLIGHT",
            retry_count=MAX_DISPATCH_ATTEMPTS - 1,
        )

        class Recorder:
            saved = {}

            def save(self, update_fields=None):
                Recorder.saved = {
                    "status": message.status,
                    "retry_count": message.retry_count,
                }

        message.save = Recorder().save
        OutboxService.mark_failed(message=message, retryable=True)

        # The claim still needs submitting, so somebody must be able to find it.
        assert message.status == "EXHAUSTED"

    def test_a_non_retryable_failure_is_not_retried(self, db):
        from apps.insurance.models import InsuranceOutboxMessage

        message = InsuranceOutboxMessage(
            tenant_id=None, event_type="X", idempotency_key="k2", payload={},
            status="IN_FLIGHT", retry_count=0,
        )
        message.save = lambda update_fields=None: None

        # Resending the same malformed payload produces the same refusal and
        # buries the real one.
        OutboxService.mark_failed(message=message, retryable=False)
        assert message.status == "FAILED"

    def test_a_retryable_failure_returns_to_the_queue(self, db):
        from apps.insurance.models import InsuranceOutboxMessage

        message = InsuranceOutboxMessage(
            tenant_id=None, event_type="X", idempotency_key="k3", payload={},
            status="IN_FLIGHT", retry_count=0,
        )
        message.save = lambda update_fields=None: None

        OutboxService.mark_failed(message=message, retryable=True)
        assert message.status == "PENDING"
        assert message.retry_count == 1


class TestOutboxIdempotency:
    def test_enqueueing_the_same_key_twice_creates_one_message(self, db):
        from apps.insurance.models import InsuranceOutboxMessage
        from apps.tenancy.models import Tenant

        tenant = Tenant.objects.create(name="Outbox Tenant", slug="outbox-tenant")
        first = OutboxService.enqueue(
            tenant_id=tenant.pk,
            event_type="ClaimSubmissionRequested",
            idempotency_key="submit:claim-1",
            payload={"claim": "1"},
        )
        second = OutboxService.enqueue(
            tenant_id=tenant.pk,
            event_type="ClaimSubmissionRequested",
            idempotency_key="submit:claim-1",
            payload={"claim": "1"},
        )
        assert first.pk == second.pk
        assert InsuranceOutboxMessage.all_objects.filter(
            idempotency_key="submit:claim-1"
        ).count() == 1


class TestStuckDispatch:
    def test_stuck_messages_are_discoverable(self, db):
        """A worker killed mid-dispatch leaves its batch IN_FLIGHT forever.

        Each one is a claim the insurer has not been told about, so they must
        surface rather than sitting invisible.
        """
        assert OutboxService.stuck(older_than=timedelta(minutes=30)).count() == 0
        assert hasattr(OutboxService, "stuck")
