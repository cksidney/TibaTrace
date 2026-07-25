"""POS payment intent and settlement ledger."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.utils import IntegrityError
from tests.test_pos_enterprise_dispensing import (  # noqa: F401
    domain,
    make_clinically_ready,
    setup_domain,
)

from apps.prescription.models import DispensingEpisode
from apps.prescription.payment_models import (
    PaymentIntent,
    PaymentReversal,
    PaymentSettlement,
    PaymentTender,
)
from apps.prescription.payment_services import (
    PaymentIntentService,
    PaymentReversalService,
    PaymentSettlementService,
    PaymentStateProjectionService,
    PaymentTenderService,
)

pytestmark = pytest.mark.django_db

DUE = Decimal("1000.00")


@pytest.fixture
def intent(domain):  # noqa: F811
    return PaymentIntentService.create(
        episode=domain["episode"],
        amount_due=DUE,
        actor=domain["cashier"],
        idempotency_key="intent-1",
        device_id="TILL-1",
        register_id="REG-1",
    )


def cash_tender(domain, intent, amount, key="t-cash"):  # noqa: F811
    return PaymentTenderService.allocate(
        intent=intent,
        tender_type="CASH",
        allocated_amount=amount,
        actor=domain["cashier"],
        idempotency_key=key,
    )


# ---------------------------------------------------------------- intent


def test_intent_creation_is_idempotent(domain, intent):  # noqa: F811
    again = PaymentIntentService.create(
        episode=domain["episode"],
        amount_due=DUE,
        actor=domain["cashier"],
        idempotency_key="intent-1",
    )
    assert again.id == intent.id
    assert PaymentIntent.all_objects.filter(dispensing_episode=domain["episode"]).count() == 1


def test_only_one_active_intent_per_episode(domain, intent):  # noqa: F811
    with pytest.raises(ValidationError, match="already has an active payment intent"):
        PaymentIntentService.create(
            episode=domain["episode"],
            amount_due=DUE,
            actor=domain["cashier"],
            idempotency_key="intent-2",
        )


def test_active_intent_uniqueness_is_enforced_by_the_database(domain, intent):  # noqa: F811
    """The service check is not the only guard."""
    with pytest.raises(IntegrityError):
        PaymentIntent.all_objects.create(
            tenant=domain["tenant"],
            branch=domain["branch"],
            dispensing_episode=domain["episode"],
            amount_due=DUE,
            status=PaymentIntent.Status.OPEN,
            idempotency_key="intent-raw",
        )


def test_intent_creation_requires_capability(domain):  # noqa: F811
    stranger = domain["witness"]
    from apps.identity.models import UserRole

    UserRole.all_objects.filter(user=stranger).delete()
    with pytest.raises(PermissionDenied):
        PaymentIntentService.create(
            episode=domain["episode"],
            amount_due=DUE,
            actor=stranger,
            idempotency_key="intent-x",
        )


# ---------------------------------------------------------------- allocation


def test_allocation_cannot_exceed_amount_due(domain, intent):  # noqa: F811
    cash_tender(domain, intent, Decimal("600.00"), key="a")
    with pytest.raises(ValidationError, match="would exceed the amount due"):
        cash_tender(domain, intent, Decimal("500.00"), key="b")


def test_allocation_must_be_positive(domain, intent):  # noqa: F811
    with pytest.raises(ValidationError, match="greater than zero"):
        cash_tender(domain, intent, Decimal("0"), key="zero")


def test_cancelled_tender_frees_its_allocation(domain, intent):  # noqa: F811
    first = cash_tender(domain, intent, Decimal("1000.00"), key="a")
    PaymentTenderService.cancel(tender=first, actor=domain["cashier"], reason="wrong method")
    # The full amount is allocatable again.
    replacement = cash_tender(domain, intent, Decimal("1000.00"), key="b")
    assert replacement.allocated_amount == DUE


# ---------------------------------------------------------------- settlement


def test_settlement_is_idempotent_on_replay(domain, intent):  # noqa: F811
    tender = cash_tender(domain, intent, DUE)
    first = PaymentSettlementService.settle_cash(
        tender=tender, cash_received=DUE, actor=domain["cashier"], idempotency_key="s-1"
    )
    replay = PaymentSettlementService.settle_cash(
        tender=tender, cash_received=DUE, actor=domain["cashier"], idempotency_key="s-1"
    )
    assert first.id == replay.id
    assert PaymentSettlement.all_objects.filter(payment_tender=tender).count() == 1


def test_settlement_cannot_exceed_tender_allocation(domain, intent):  # noqa: F811
    tender = cash_tender(domain, intent, Decimal("400.00"))
    with pytest.raises(ValidationError, match="exceed the tender allocation"):
        PaymentSettlementService.record(
            tender=tender,
            amount=Decimal("500.00"),
            source=PaymentSettlement.Source.CASH,
            idempotency_key="over",
        )


def test_settlement_is_immutable(domain, intent):  # noqa: F811
    tender = cash_tender(domain, intent, DUE)
    settlement = PaymentSettlementService.settle_cash(
        tender=tender, cash_received=DUE, actor=domain["cashier"], idempotency_key="s-1"
    )
    settlement.amount = Decimal("1.00")
    with pytest.raises(ValueError, match="immutable"):
        settlement.save()


# ---------------------------------------------------------------- cash


def test_cash_change_is_calculated_once_and_stored(domain, intent):  # noqa: F811
    tender = cash_tender(domain, intent, DUE)
    PaymentSettlementService.settle_cash(
        tender=tender,
        cash_received=Decimal("1200.00"),
        actor=domain["cashier"],
        idempotency_key="s-1",
        shift=None,
        register_id="REG-1",
    )
    tender.refresh_from_db()
    assert tender.cash_received == Decimal("1200.00")
    assert tender.change_due == Decimal("200.00")
    assert tender.status == PaymentTender.Status.SETTLED


def test_cash_below_allocation_is_refused(domain, intent):  # noqa: F811
    tender = cash_tender(domain, intent, DUE)
    with pytest.raises(ValidationError, match="less than the allocated amount"):
        PaymentSettlementService.settle_cash(
            tender=tender,
            cash_received=Decimal("900.00"),
            actor=domain["cashier"],
            idempotency_key="s-short",
        )


# ---------------------------------------------------------------- card


def test_card_confirmation_records_approval_reference(domain, intent):  # noqa: F811
    tender = PaymentTenderService.allocate(
        intent=intent,
        tender_type="CARD",
        allocated_amount=DUE,
        actor=domain["cashier"],
        idempotency_key="t-card",
    )
    PaymentSettlementService.confirm_card(
        tender=tender,
        approval_reference="APPROVAL-99",
        approved_amount=DUE,
        actor=domain["cashier"],
        idempotency_key="s-card",
    )
    tender.refresh_from_db()
    assert tender.external_reference == "APPROVAL-99"
    assert tender.status == PaymentTender.Status.SETTLED


def test_card_approval_reference_cannot_be_reused(domain, intent):  # noqa: F811
    """One real-world approval must not be counted twice."""
    tender_a = PaymentTenderService.allocate(
        intent=intent,
        tender_type="CARD",
        allocated_amount=Decimal("500.00"),
        actor=domain["cashier"],
        idempotency_key="t-a",
    )
    tender_b = PaymentTenderService.allocate(
        intent=intent,
        tender_type="CARD",
        allocated_amount=Decimal("500.00"),
        actor=domain["cashier"],
        idempotency_key="t-b",
    )
    PaymentSettlementService.confirm_card(
        tender=tender_a,
        approval_reference="DUP-REF",
        approved_amount=Decimal("500.00"),
        actor=domain["cashier"],
        idempotency_key="s-a",
    )
    with pytest.raises(IntegrityError):
        PaymentSettlementService.confirm_card(
            tender=tender_b,
            approval_reference="DUP-REF",
            approved_amount=Decimal("500.00"),
            actor=domain["cashier"],
            idempotency_key="s-b",
        )


# ---------------------------------------------------------------- projection


def test_projection_marks_episode_partially_paid_then_paid(domain, intent):  # noqa: F811
    episode = domain["episode"]
    first = cash_tender(domain, intent, Decimal("400.00"), key="t1")
    PaymentSettlementService.settle_cash(
        tender=first, cash_received=Decimal("400.00"), actor=domain["cashier"], idempotency_key="s1"
    )
    episode.refresh_from_db()
    assert episode.payment_state == "PARTIALLY_PAID"

    second = cash_tender(domain, intent, Decimal("600.00"), key="t2")
    PaymentSettlementService.settle_cash(
        tender=second, cash_received=Decimal("600.00"), actor=domain["cashier"], idempotency_key="s2"
    )
    episode.refresh_from_db()
    assert episode.payment_state == "PAID"
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.SETTLED


def test_partially_paid_episode_cannot_pass_the_supply_gate(domain, intent):  # noqa: F811
    """The central rule: part-payment must not release stock."""
    episode = domain["episode"]
    tender = cash_tender(domain, intent, Decimal("400.00"))
    PaymentSettlementService.settle_cash(
        tender=tender, cash_received=Decimal("400.00"), actor=domain["cashier"], idempotency_key="s1"
    )
    episode.refresh_from_db()
    assert episode.payment_state == "PARTIALLY_PAID"
    assert (
        episode.payment_state not in DispensingEpisode.PAYMENT_STATES_PERMITTING_SUPPLY
    )

    from apps.prescription.pos_dispensing_services import PosCollectionService

    make_clinically_ready(domain)
    episode.status = "READY_FOR_SUPPLY"
    episode.save(update_fields=["status"])
    with pytest.raises(ValidationError, match="Payment gate"):
        PosCollectionService.confirm_collection(
            episode=episode,
            collector_name="John Doe",
            actor=domain["pharmacist"],
            idempotency_key="collect-1",
        )


def test_zero_amount_intent_projects_not_required(domain):  # noqa: F811
    intent = PaymentIntentService.create(
        episode=domain["episode"],
        amount_due=Decimal("0"),
        actor=domain["cashier"],
        idempotency_key="intent-zero",
    )
    domain["episode"].refresh_from_db()
    assert domain["episode"].payment_state == "NOT_REQUIRED"
    assert intent.status == PaymentIntent.Status.SETTLED


# ---------------------------------------------------------------- reversal


def test_reversal_requires_a_different_approver(domain, intent):  # noqa: F811
    tender = cash_tender(domain, intent, DUE)
    settlement = PaymentSettlementService.settle_cash(
        tender=tender, cash_received=DUE, actor=domain["cashier"], idempotency_key="s-1"
    )
    reversal = PaymentReversalService.request(
        settlement=settlement,
        amount=DUE,
        reason="cashier error",
        actor=domain["pharmacist"],
        idempotency_key="r-1",
    )
    with pytest.raises(ValidationError, match="other than the requester"):
        PaymentReversalService.complete(reversal=reversal, actor=domain["pharmacist"])


def test_pending_reversal_blocks_supply_and_completion_reverses_state(domain, intent):  # noqa: F811
    episode = domain["episode"]
    tender = cash_tender(domain, intent, DUE)
    settlement = PaymentSettlementService.settle_cash(
        tender=tender, cash_received=DUE, actor=domain["cashier"], idempotency_key="s-1"
    )
    episode.refresh_from_db()
    assert episode.payment_state == "PAID"

    reversal = PaymentReversalService.request(
        settlement=settlement,
        amount=DUE,
        reason="patient refused supply",
        actor=domain["pharmacist"],
        idempotency_key="r-1",
    )
    episode.refresh_from_db()
    assert episode.payment_state == "REVERSAL_PENDING"
    assert episode.payment_state not in DispensingEpisode.PAYMENT_STATES_PERMITTING_SUPPLY

    PaymentReversalService.complete(reversal=reversal, actor=domain["witness"])
    episode.refresh_from_db()
    assert episode.payment_state == "REVERSED"
    assert PaymentReversal.all_objects.get(pk=reversal.pk).approved_by == domain["witness"]


def test_reversal_cannot_exceed_the_settled_amount(domain, intent):  # noqa: F811
    tender = cash_tender(domain, intent, DUE)
    settlement = PaymentSettlementService.settle_cash(
        tender=tender, cash_received=DUE, actor=domain["cashier"], idempotency_key="s-1"
    )
    with pytest.raises(ValidationError, match="exceed the settled amount"):
        PaymentReversalService.request(
            settlement=settlement,
            amount=Decimal("1500.00"),
            reason="too much",
            actor=domain["pharmacist"],
            idempotency_key="r-big",
        )


# ---------------------------------------------------------------- split tender


@pytest.mark.parametrize(
    "combination",
    [
        [("CASH", "400.00"), ("CARD", "600.00")],
        [("CASH", "300.00"), ("MPESA", "700.00")],
        [("CARD", "500.00"), ("MPESA", "500.00")],
        [("CASH", "200.00"), ("CARD", "300.00"), ("MPESA", "500.00")],
    ],
)
def test_split_tender_allocations_must_total_the_amount_due(domain, intent, combination):  # noqa: F811
    allocated = Decimal("0")
    for index, (tender_type, amount) in enumerate(combination):
        tender = PaymentTenderService.allocate(
            intent=intent,
            tender_type=tender_type,
            allocated_amount=Decimal(amount),
            actor=domain["cashier"],
            idempotency_key=f"t-{index}",
            provider="FAKE" if tender_type == "MPESA" else "MANUAL",
        )
        allocated += tender.allocated_amount
    assert allocated == DUE


def test_failed_component_does_not_erase_settled_tenders(domain, intent):  # noqa: F811
    cash = cash_tender(domain, intent, Decimal("400.00"), key="t-cash")
    PaymentSettlementService.settle_cash(
        tender=cash, cash_received=Decimal("400.00"), actor=domain["cashier"], idempotency_key="s-cash"
    )
    card = PaymentTenderService.allocate(
        intent=intent,
        tender_type="CARD",
        allocated_amount=Decimal("600.00"),
        actor=domain["cashier"],
        idempotency_key="t-card",
    )
    PaymentTenderService.cancel(tender=card, actor=domain["cashier"], reason="declined")

    intent.refresh_from_db()
    assert intent.amount_settled == Decimal("400.00")
    domain["episode"].refresh_from_db()
    assert domain["episode"].payment_state == "PARTIALLY_PAID"

    # A replacement tender can settle the remainder.
    replacement = cash_tender(domain, intent, Decimal("600.00"), key="t-replace")
    PaymentSettlementService.settle_cash(
        tender=replacement,
        cash_received=Decimal("600.00"),
        actor=domain["cashier"],
        idempotency_key="s-replace",
    )
    domain["episode"].refresh_from_db()
    assert domain["episode"].payment_state == "PAID"


def test_projection_recomputes_totals_rather_than_incrementing(domain, intent):  # noqa: F811
    """Totals are derived, so a corrupted cached value self-heals."""
    tender = cash_tender(domain, intent, DUE)
    PaymentSettlementService.settle_cash(
        tender=tender, cash_received=DUE, actor=domain["cashier"], idempotency_key="s-1"
    )
    PaymentIntent.all_objects.filter(pk=intent.pk).update(amount_settled=Decimal("0"))
    PaymentStateProjectionService.project(intent=intent)
    intent.refresh_from_db()
    assert intent.amount_settled == DUE


def test_cashier_cannot_reverse_a_settlement(domain, intent):  # noqa: F811
    """Taking money back is supervisory; accepting it is not."""
    tender = cash_tender(domain, intent, DUE)
    settlement = PaymentSettlementService.settle_cash(
        tender=tender, cash_received=DUE, actor=domain["cashier"], idempotency_key="s-1"
    )
    with pytest.raises(PermissionDenied):
        PaymentReversalService.request(
            settlement=settlement,
            amount=DUE,
            reason="unauthorised attempt",
            actor=domain["cashier"],
            idempotency_key="r-cashier",
        )
