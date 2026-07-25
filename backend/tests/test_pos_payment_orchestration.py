"""Provider settlement and split-tender orchestration.

The recurring hazard is double-counting: a provider may deliver the same
callback twice, deliver it before the initiation response was persisted, or
deliver it long after a timeout was declared. Each must converge on exactly one
settlement.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from tests.test_pos_enterprise_dispensing import (  # noqa: F401
    domain,
    make_clinically_ready,
    setup_domain,
)

from apps.prescription.payment_models import (
    PaymentAttempt,
    PaymentProviderEvent,
    PaymentSettlement,
)
from apps.prescription.payment_orchestration import (
    PaymentAttemptService,
    PaymentEventService,
    SplitTenderService,
)
from apps.prescription.payment_providers import (
    FakeProviderAdapter,
    FakeProviderScenario,
    get_adapter,
)
from apps.prescription.payment_services import PaymentIntentService, PaymentTenderService

pytestmark = pytest.mark.django_db

DUE = Decimal("1000.00")


@pytest.fixture
def intent(domain):  # noqa: F811
    return PaymentIntentService.create(
        episode=domain["episode"],
        amount_due=DUE,
        actor=domain["cashier"],
        idempotency_key="intent-orch",
    )


def tender(domain, intent, amount, key, tender_type="MPESA", provider="FAKE"):  # noqa: F811
    return PaymentTenderService.allocate(
        intent=intent,
        tender_type=tender_type,
        allocated_amount=amount,
        actor=domain["cashier"],
        idempotency_key=key,
        provider=provider,
    )


def success_event(adapter, attempt, amount=None):
    event = adapter.query_status(attempt=attempt)
    if amount is not None:
        from apps.prescription.payment_providers import ProviderEvent

        event = ProviderEvent(
            provider_reference=event.provider_reference,
            request_reference=event.request_reference,
            event_type=event.event_type,
            status="SUCCEEDED",
            amount=amount,
            account_reference=event.account_reference,
            event_id=event.event_id,
        )
    return event


# ------------------------------------------------------------------ adapters


def test_unregistered_provider_cannot_be_selected():
    """A tender must not be settleable through an unimplemented provider."""
    with pytest.raises(ValueError, match="No payment adapter"):
        get_adapter("MPESA")


def test_fake_provider_rejects_an_unknown_scenario():
    with pytest.raises(ValueError, match="Unknown fake provider scenario"):
        FakeProviderAdapter(scenario="NOT_A_SCENARIO")


def test_initiation_is_not_settlement(domain, intent):  # noqa: F811
    """Accepting a request tells us nothing about whether money arrived."""
    t = tender(domain, intent, DUE, "t-1")
    attempt, result = PaymentAttemptService.initiate(
        tender=t, actor=domain["cashier"], adapter=FakeProviderAdapter()
    )
    assert result.accepted is True
    assert attempt.status == PaymentAttempt.Status.ACCEPTED
    # No settlement, and the episode is not paid.
    assert not PaymentSettlement.all_objects.filter(payment_tender=t).exists()
    domain["episode"].refresh_from_db()
    assert domain["episode"].payment_state != "PAID"


def test_declined_initiation_does_not_settle(domain, intent):  # noqa: F811
    t = tender(domain, intent, DUE, "t-1")
    attempt, result = PaymentAttemptService.initiate(
        tender=t,
        actor=domain["cashier"],
        adapter=FakeProviderAdapter(scenario=FakeProviderScenario.DECLINED),
    )
    assert result.accepted is False
    assert result.retryable is False
    assert attempt.status == PaymentAttempt.Status.FAILED


def test_provider_unavailable_is_retryable(domain, intent):  # noqa: F811
    """Nothing was collected, so retrying is safe."""
    t = tender(domain, intent, DUE, "t-1")
    _, result = PaymentAttemptService.initiate(
        tender=t,
        actor=domain["cashier"],
        adapter=FakeProviderAdapter(scenario=FakeProviderScenario.PROVIDER_UNAVAILABLE),
    )
    assert result.accepted is False
    assert result.retryable is True


# ------------------------------------------------------------------ events


def test_successful_event_settles_once(domain, intent):  # noqa: F811
    t = tender(domain, intent, DUE, "t-1")
    adapter = FakeProviderAdapter()
    attempt, _ = PaymentAttemptService.initiate(tender=t, actor=domain["cashier"], adapter=adapter)

    record, settlement = PaymentEventService.apply(
        tenant=domain["tenant"], provider_code="FAKE", event=success_event(adapter, attempt)
    )
    assert record.processing_status == PaymentProviderEvent.ProcessingStatus.PROCESSED
    assert settlement is not None
    domain["episode"].refresh_from_db()
    assert domain["episode"].payment_state == "PAID"


def test_duplicate_callback_does_not_settle_twice(domain, intent):  # noqa: F811
    """Providers redeliver. That is normal, and must not double-count."""
    t = tender(domain, intent, DUE, "t-1")
    adapter = FakeProviderAdapter()
    attempt, _ = PaymentAttemptService.initiate(tender=t, actor=domain["cashier"], adapter=adapter)
    event = success_event(adapter, attempt)

    PaymentEventService.apply(tenant=domain["tenant"], provider_code="FAKE", event=event)
    record, settlement = PaymentEventService.apply(
        tenant=domain["tenant"], provider_code="FAKE", event=event
    )

    assert record.processing_status == PaymentProviderEvent.ProcessingStatus.DUPLICATE
    assert settlement is None
    assert PaymentSettlement.all_objects.filter(payment_tender=t).count() == 1


def test_unauthenticated_event_is_recorded_but_never_applied(domain, intent):  # noqa: F811
    """An event we cannot authenticate could otherwise mint a settlement."""
    t = tender(domain, intent, DUE, "t-1")
    adapter = FakeProviderAdapter()
    attempt, _ = PaymentAttemptService.initiate(tender=t, actor=domain["cashier"], adapter=adapter)

    record, settlement = PaymentEventService.apply(
        tenant=domain["tenant"],
        provider_code="FAKE",
        event=success_event(adapter, attempt),
        authenticated=False,
    )
    assert record.processing_status == PaymentProviderEvent.ProcessingStatus.REJECTED
    assert settlement is None
    assert not PaymentSettlement.all_objects.filter(payment_tender=t).exists()


def test_event_signature_must_match(domain):  # noqa: F811
    adapter = FakeProviderAdapter(secret="the-real-secret")
    payload = {"status": "SUCCEEDED", "amount": "100.00"}
    good = adapter.expected_signature(payload)

    assert adapter.authenticate_event(headers={"X-Fake-Signature": good}, payload=payload) is True
    assert adapter.authenticate_event(headers={"X-Fake-Signature": "forged"}, payload=payload) is False
    # An unsigned event is refused rather than treated as trusted.
    assert adapter.authenticate_event(headers={}, payload=payload) is False


def test_wrong_amount_is_refused_rather_than_absorbed(domain, intent):  # noqa: F811
    """Settling a mismatch would leave the ledger disagreeing with the provider."""
    t = tender(domain, intent, DUE, "t-1")
    adapter = FakeProviderAdapter(scenario=FakeProviderScenario.WRONG_AMOUNT)
    attempt, _ = PaymentAttemptService.initiate(tender=t, actor=domain["cashier"], adapter=adapter)

    record, settlement = PaymentEventService.apply(
        tenant=domain["tenant"], provider_code="FAKE", event=success_event(adapter, attempt)
    )
    assert record.processing_status == PaymentProviderEvent.ProcessingStatus.REJECTED
    assert "Amount mismatch" in record.processing_error
    assert settlement is None


def test_event_for_an_unknown_request_is_held_for_reconciliation(domain):  # noqa: F811
    """Callback-before-initiation must not lose a real payment."""
    from apps.prescription.payment_providers import ProviderEvent

    record, settlement = PaymentEventService.apply(
        tenant=domain["tenant"],
        provider_code="FAKE",
        event=ProviderEvent(
            provider_reference="FAKE-UNKNOWN",
            request_reference="REQ-NEVER-SEEN",
            event_type="PAYMENT",
            status="SUCCEEDED",
            amount=Decimal("100.00"),
            event_id="EVT-ORPHAN",
        ),
    )
    assert record.processing_status == PaymentProviderEvent.ProcessingStatus.UNMATCHED
    assert settlement is None


def test_pending_event_does_not_settle(domain, intent):  # noqa: F811
    t = tender(domain, intent, DUE, "t-1")
    adapter = FakeProviderAdapter(scenario=FakeProviderScenario.PENDING_THEN_SUCCESS)
    attempt, _ = PaymentAttemptService.initiate(tender=t, actor=domain["cashier"], adapter=adapter)

    _, settlement = PaymentEventService.apply(
        tenant=domain["tenant"], provider_code="FAKE", event=adapter.query_status(attempt=attempt)
    )
    assert settlement is None
    domain["episode"].refresh_from_db()
    assert domain["episode"].payment_state != "PAID"


# ------------------------------------------------------------- split tender


def test_split_across_three_tenders_settles_to_paid(domain, intent):  # noqa: F811
    cash = tender(domain, intent, Decimal("200.00"), "t-cash", "CASH", "MANUAL")
    card = tender(domain, intent, Decimal("300.00"), "t-card", "CARD", "MANUAL")
    mobile = tender(domain, intent, Decimal("500.00"), "t-mpesa", "MPESA", "FAKE")

    from apps.prescription.payment_services import PaymentSettlementService

    PaymentSettlementService.settle_cash(
        tender=cash, cash_received=Decimal("200.00"), actor=domain["cashier"], idempotency_key="s-cash"
    )
    PaymentSettlementService.confirm_card(
        tender=card,
        approval_reference="APPROVAL-1",
        approved_amount=Decimal("300.00"),
        actor=domain["cashier"],
        idempotency_key="s-card",
    )
    adapter = FakeProviderAdapter()
    attempt, _ = PaymentAttemptService.initiate(
        tender=mobile, actor=domain["cashier"], adapter=adapter
    )
    PaymentEventService.apply(
        tenant=domain["tenant"], provider_code="FAKE", event=success_event(adapter, attempt)
    )

    summary = SplitTenderService.finalise(intent=intent)
    assert summary["settled"] == DUE
    assert summary["remaining"] == Decimal("0")
    assert summary["fully_settled"] is True
    domain["episode"].refresh_from_db()
    assert domain["episode"].payment_state == "PAID"


def test_partial_split_leaves_the_episode_partially_paid(domain, intent):  # noqa: F811
    from apps.prescription.payment_services import PaymentSettlementService

    cash = tender(domain, intent, Decimal("400.00"), "t-cash", "CASH", "MANUAL")
    tender(domain, intent, Decimal("600.00"), "t-mpesa", "MPESA", "FAKE")
    PaymentSettlementService.settle_cash(
        tender=cash, cash_received=Decimal("400.00"), actor=domain["cashier"], idempotency_key="s-cash"
    )

    summary = SplitTenderService.finalise(intent=intent)
    assert summary["settled"] == Decimal("400.00")
    assert summary["remaining"] == Decimal("600.00")
    assert summary["fully_settled"] is False
    domain["episode"].refresh_from_db()
    assert domain["episode"].payment_state == "PARTIALLY_PAID"


def test_a_pending_provider_tender_is_not_counted_as_settled(domain, intent):  # noqa: F811
    """A pending attempt must never look like money in the till."""
    mobile = tender(domain, intent, DUE, "t-mpesa", "MPESA", "FAKE")
    PaymentAttemptService.initiate(
        tender=mobile,
        actor=domain["cashier"],
        adapter=FakeProviderAdapter(scenario=FakeProviderScenario.PENDING_THEN_SUCCESS),
    )
    summary = SplitTenderService.summary(intent=intent)
    assert summary["settled"] == Decimal("0")
    assert summary["pending"] == DUE
    assert summary["fully_settled"] is False


def test_failed_component_can_be_replaced_without_losing_settled_value(domain, intent):  # noqa: F811
    from apps.prescription.payment_services import PaymentSettlementService

    cash = tender(domain, intent, Decimal("400.00"), "t-cash", "CASH", "MANUAL")
    PaymentSettlementService.settle_cash(
        tender=cash, cash_received=Decimal("400.00"), actor=domain["cashier"], idempotency_key="s-cash"
    )
    failing = tender(domain, intent, Decimal("600.00"), "t-mpesa", "MPESA", "FAKE")

    replacement = SplitTenderService.replace_failed_tender(
        tender=failing,
        actor=domain["cashier"],
        tender_type="CASH",
        idempotency_key="t-replacement",
    )
    assert replacement.allocated_amount == Decimal("600.00")

    summary = SplitTenderService.summary(intent=intent)
    # The already-settled cash survives the replacement.
    assert summary["settled"] == Decimal("400.00")
    assert summary["fully_allocated"] is True


def test_a_settled_tender_cannot_be_replaced(domain, intent):  # noqa: F811
    from apps.prescription.payment_services import PaymentSettlementService

    cash = tender(domain, intent, DUE, "t-cash", "CASH", "MANUAL")
    PaymentSettlementService.settle_cash(
        tender=cash, cash_received=DUE, actor=domain["cashier"], idempotency_key="s-cash"
    )
    with pytest.raises(ValidationError, match="reverse it rather than replacing"):
        SplitTenderService.replace_failed_tender(
            tender=cash,
            actor=domain["cashier"],
            tender_type="CARD",
            idempotency_key="t-replacement",
        )


def test_allocation_cannot_exceed_the_amount_due_across_tenders(domain, intent):  # noqa: F811
    tender(domain, intent, Decimal("600.00"), "t-1", "CASH", "MANUAL")
    with pytest.raises(ValidationError, match="exceed the amount due"):
        tender(domain, intent, Decimal("500.00"), "t-2", "CASH", "MANUAL")


def test_summary_reports_unallocated_balance(domain, intent):  # noqa: F811
    tender(domain, intent, Decimal("300.00"), "t-1", "CASH", "MANUAL")
    summary = SplitTenderService.summary(intent=intent)
    assert summary["unallocated"] == Decimal("700.00")
    assert summary["fully_allocated"] is False
