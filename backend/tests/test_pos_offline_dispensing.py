"""Offline dispensing eligibility and sync.

A disconnected terminal cannot re-screen, cannot see stock moving elsewhere and
cannot consult a pharmacist. These tests pin the default to "no", and pin which
narrow cases are permitted.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from tests.test_pos_enterprise_dispensing import (  # noqa: F401
    domain,
    make_clinically_ready,
    setup_domain,
)

from apps.prescription.offline_dispensing import (
    MAX_STOCK_SNAPSHOT_AGE,
    OFFLINE_ACTION_ACCEPT_CASH,
    OFFLINE_ACTION_DISPENSE,
    OfflineDispensingPolicy,
    OfflineSyncService,
)

pytestmark = pytest.mark.django_db


class FakeScreening:
    def __init__(self, *, status="COMPLETE", safe=True, expires_at=None):
        self.status = status
        self.safe_to_proceed = safe
        self.expires_at = expires_at


def fresh_snapshot():
    return timezone.now() - timedelta(minutes=5)


def evaluate(domain, **overrides):  # noqa: F811
    episode = domain["episode"]
    episode.payment_state = overrides.pop("payment_state", "PAID")
    params = {
        "episode": episode,
        "screening": FakeScreening(),
        "stock_snapshot_at": fresh_snapshot(),
    }
    params.update(overrides)
    return OfflineDispensingPolicy.evaluate(**params)


# ------------------------------------------------------------- eligibility


def test_a_clean_episode_is_permitted_offline(domain):  # noqa: F811
    result = evaluate(domain)
    assert result.permitted is True
    assert result.state == "OFFLINE_ALLOWED"
    assert OFFLINE_ACTION_DISPENSE in result.permitted_actions


def test_controlled_medicine_is_never_dispensed_offline(domain):  # noqa: F811
    """The register, witness and custody checks all depend on the server."""
    rx = domain["rx"]
    rx.is_controlled_medicine = True
    rx.save(update_fields=["is_controlled_medicine"])
    domain["episode"].refresh_from_db()

    result = evaluate(domain)
    assert result.blocked is True
    assert any("Controlled medicines" in reason for reason in result.reasons)


def test_missing_screening_blocks_offline_supply(domain):  # noqa: F811
    result = evaluate(domain, screening=None)
    assert result.blocked is True
    assert any("No clinical screening" in reason for reason in result.reasons)


def test_unsafe_screening_blocks_offline_supply(domain):  # noqa: F811
    result = evaluate(domain, screening=FakeScreening(safe=False))
    assert result.blocked is True


def test_incomplete_screening_blocks_offline_supply(domain):  # noqa: F811
    result = evaluate(domain, screening=FakeScreening(status="PENDING"))
    assert result.blocked is True


def test_expired_screening_blocks_offline_supply(domain):  # noqa: F811
    result = evaluate(
        domain, screening=FakeScreening(expires_at=timezone.now() - timedelta(minutes=1))
    )
    assert result.blocked is True
    assert any("expired" in reason for reason in result.reasons)


@pytest.mark.parametrize("state", ["PENDING", "PARTIALLY_PAID", "FAILED", "REVERSED"])
def test_unsettled_payment_blocks_offline_supply(domain, state):  # noqa: F811
    """A disconnected till cannot resolve a payment the server has not settled."""
    result = evaluate(domain, payment_state=state)
    assert result.blocked is True


def test_a_stale_stock_snapshot_blocks_supply(domain):  # noqa: F811
    old = timezone.now() - MAX_STOCK_SNAPSHOT_AGE - timedelta(minutes=1)
    result = evaluate(domain, stock_snapshot_at=old)
    assert result.blocked is True
    assert any("stock snapshot" in reason for reason in result.reasons)


def test_missing_stock_snapshot_blocks_supply(domain):  # noqa: F811
    result = evaluate(domain, stock_snapshot_at=None)
    assert result.blocked is True


def test_tenant_policy_can_disable_offline_entirely(domain):  # noqa: F811
    result = evaluate(domain, tenant_allows_offline=False)
    assert result.blocked is True


def test_an_unauthorised_device_is_blocked(domain):  # noqa: F811
    result = evaluate(domain, device_authorised=False)
    assert result.blocked is True


def test_every_blocking_reason_is_reported_not_just_the_first(domain):  # noqa: F811
    """An operator should see the whole picture, not fix one and find another."""
    result = evaluate(
        domain,
        screening=None,
        stock_snapshot_at=None,
        payment_state="PENDING",
        device_authorised=False,
    )
    assert len(result.reasons) >= 4


def test_offline_payment_is_limited_to_cash(domain):  # noqa: F811
    """A provider tender cannot be confirmed without the provider."""
    result = evaluate(domain)
    assert OFFLINE_ACTION_ACCEPT_CASH in result.permitted_actions
    assert not any("MPESA" in action or "CARD" in action for action in result.permitted_actions)


# ------------------------------------------------------------------- sync


def test_sync_requires_an_idempotency_key(domain):  # noqa: F811
    with pytest.raises(ValidationError):
        OfflineSyncService.submit_supply(
            episode=domain["episode"],
            actor=domain["pharmacist"],
            idempotency_key="",
            performed_at=timezone.now(),
            context_hash="ctx",
        )


def test_replayed_sync_is_a_success_not_a_conflict(domain):  # noqa: F811
    """A device that never saw the acknowledgement will retry. That is normal."""
    data = domain
    make_clinically_ready(data)
    episode = data["episode"]
    episode.status = "READY_FOR_SUPPLY"
    episode.payment_state = "PAID"
    episode.save(update_fields=["status", "payment_state"])

    first = OfflineSyncService.submit_supply(
        episode=episode,
        actor=data["pharmacist"],
        idempotency_key="offline-1",
        performed_at=timezone.now(),
        context_hash="ctx",
    )
    assert first.accepted is True
    assert first.status == "RECONCILED"

    replay = OfflineSyncService.submit_supply(
        episode=episode,
        actor=data["pharmacist"],
        idempotency_key="offline-1",
        performed_at=timezone.now(),
        context_hash="ctx",
    )
    assert replay.accepted is True
    assert replay.status == "DUPLICATE"

    from apps.prescription.models import MedicineSupply

    assert MedicineSupply.all_objects.filter(episode=episode).count() == 1


def test_an_unverifiable_package_is_a_conflict_not_an_acceptance(domain):  # noqa: F811
    """The device acted on something we cannot vouch for."""
    from apps.cds.offline_package_signing import VerificationResult

    outcome = OfflineSyncService.submit_supply(
        episode=domain["episode"],
        actor=domain["pharmacist"],
        idempotency_key="offline-bad",
        performed_at=timezone.now(),
        context_hash="ctx",
        package_verification=VerificationResult.failure("OFFLINE_PACKAGE_EXPIRED", "expired"),
    )
    assert outcome.accepted is False
    assert outcome.status == "CONFLICT"
    assert outcome.conflict_code == "OFFLINE_PACKAGE_EXPIRED"


def test_a_server_refusal_at_sync_becomes_a_conflict(domain):  # noqa: F811
    """The world may have moved while the device was away."""
    # No clinical readiness, so the authoritative supply path refuses.
    outcome = OfflineSyncService.submit_supply(
        episode=domain["episode"],
        actor=domain["pharmacist"],
        idempotency_key="offline-refused",
        performed_at=timezone.now(),
        context_hash="ctx",
    )
    assert outcome.accepted is False
    assert outcome.status == "CONFLICT"
    assert outcome.conflict_code == "SERVER_REFUSED_OFFLINE_SUPPLY"


def test_conflicts_route_to_review(domain):  # noqa: F811
    from apps.prescription.offline_dispensing import SyncOutcome

    conflict = SyncOutcome(accepted=False, status="CONFLICT", message="")
    resolved = SyncOutcome(accepted=True, status="RECONCILED", message="")
    assert OfflineSyncService.classify_conflict(outcome=conflict) == "REQUIRES_REVIEW"
    assert OfflineSyncService.classify_conflict(outcome=resolved) == "RESOLVED"
