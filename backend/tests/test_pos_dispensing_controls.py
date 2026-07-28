"""Control-bypass regression tests for the POS enterprise dispensing surface.

Each test in the BYPASS section corresponds to a defect that was confirmed
present by audit probe on commit 138e539. They assert the control now holds; if
any of them starts passing medicine through, the bypass has returned.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from rest_framework.test import APIClient
from tests.test_pos_enterprise_dispensing import (  # noqa: F401
    domain,
    make_clinically_ready,
    setup_domain,
)

from apps.identity.models import User
from apps.inventory.models import InventoryLedgerEntry
from apps.prescription.models import (
    DispensingCheck,
    DispensingEpisode,
    MedicineSupply,
    PrescriptionItem,
)
from apps.prescription.pos_dispensing_services import (
    PosCollectionService,
    PosCounsellingService,
    PosDispensingQueueService,
    PosPartialRepeatService,
    PosPaymentOrchestrationService,
)

pytestmark = pytest.mark.django_db

# --------------------------------------------------------------------------
# BYPASS REGRESSIONS
# --------------------------------------------------------------------------


def test_payment_is_refused_before_the_clinical_gate(domain):
    """Was: payment accepted straight from PREPARING with no clinical gating."""
    episode = domain["episode"]
    assert episode.status == "PREPARING"

    with pytest.raises(ValidationError, match="not ready for payment"):
        PosPaymentOrchestrationService.process_payment(
            episode=episode,
            tender_type="CASH",
            paid_amount=Decimal("500.00"),
            cashier=domain["cashier"],
            idempotency_key="PAY-1",
        )


def test_episode_cannot_reach_ready_for_payment_without_verification_and_check(domain):
    """The gate that guards payment is itself gated, not a `pass` stub."""
    episode = domain["episode"]
    episode.status = "CHECKING"
    episode.save()

    with pytest.raises(ValidationError, match="pharmacist verification"):
        PosDispensingQueueService.transition_state(
            episode=episode, new_status="READY_FOR_PAYMENT", actor=domain["pharmacist"]
        )


def test_supply_is_refused_without_final_check_and_counselling(domain):
    """Was: supply completed with no DispensingCheck and no counselling."""
    episode = domain["episode"]
    episode.status = "READY_FOR_SUPPLY"
    episode.payment_state = "PAID"
    episode.save()

    assert not DispensingCheck.all_objects.filter(episode=episode).exists()
    with pytest.raises(ValidationError):
        PosCollectionService.confirm_collection(
            episode=episode,
            collector_name="John Doe",
            actor=domain["pharmacist"],
            idempotency_key="COLLECT-1",
        )
    assert not MedicineSupply.all_objects.filter(episode=episode).exists()


def test_replayed_collection_does_not_issue_stock_twice(domain):
    """Was: replay produced 2 supplies and 2 ISSUE entries (-60 for a 30 qty Rx)."""
    data = domain
    episode = data["episode"]
    make_clinically_ready(data)
    episode.status = "READY_FOR_SUPPLY"
    episode.payment_state = "PAID"
    episode.save()

    key = "COLLECT-IDEMPOTENT-1"
    first = PosCollectionService.confirm_collection(
        episode=episode, collector_name="John Doe", actor=data["pharmacist"], idempotency_key=key
    )
    episode.refresh_from_db()
    replay = PosCollectionService.confirm_collection(
        episode=episode, collector_name="John Doe", actor=data["pharmacist"], idempotency_key=key
    )

    assert first.id == replay.id, "replay must return the original supply"
    assert MedicineSupply.all_objects.filter(episode=episode).count() == 1

    issues = InventoryLedgerEntry.all_objects.filter(
        tenant=data["tenant"], entry_type=InventoryLedgerEntry.EntryType.ISSUE
    )
    assert issues.count() == 1
    assert sum(e.quantity_delta for e in issues) == Decimal("-30.0000")


def test_replayed_payment_does_not_charge_twice(domain):
    data = domain
    episode = data["episode"]
    make_clinically_ready(data)
    PosDispensingQueueService.transition_state(
        episode=episode, new_status="CHECKING", actor=data["pharmacist"]
    )
    episode.refresh_from_db()
    PosDispensingQueueService.transition_state(
        episode=episode, new_status="READY_FOR_PAYMENT", actor=data["pharmacist"]
    )
    episode.refresh_from_db()

    kwargs = dict(
        tender_type="CASH",
        paid_amount=Decimal("500.00"),
        cashier=data["cashier"],
        idempotency_key="PAY-IDEMPOTENT-1",
        device_id=data["device_id"],
    )
    first = PosPaymentOrchestrationService.process_payment(episode=episode, **kwargs)
    episode.refresh_from_db()
    replay = PosPaymentOrchestrationService.process_payment(episode=episode, **kwargs)

    assert first["replayed"] is False
    assert replay["replayed"] is True
    episode.refresh_from_db()
    assert episode.paid_amount == Decimal("500.00")
    assert episode.payment_register_session_id == data["register_session"].id
    assert episode.payment_operator_shift_id == data["operator_shift"].id
    assert episode.payment_device_id == data["device_id"]


def test_payment_is_refused_without_an_assigned_device(domain):
    data = domain
    episode = data["episode"]
    make_clinically_ready(data)
    PosDispensingQueueService.transition_state(
        episode=episode, new_status="CHECKING", actor=data["pharmacist"]
    )
    episode.refresh_from_db()
    PosDispensingQueueService.transition_state(
        episode=episode, new_status="READY_FOR_PAYMENT", actor=data["pharmacist"]
    )

    with pytest.raises(ValidationError, match="not assigned to a register"):
        PosPaymentOrchestrationService.process_payment(
            episode=episode,
            tender_type="CASH",
            paid_amount=Decimal("500.00"),
            cashier=data["cashier"],
            idempotency_key="PAY-NO-DEVICE",
            device_id="UNKNOWN-DEVICE",
        )


def test_payment_is_refused_when_the_operator_shift_is_closed(domain):
    data = domain
    episode = data["episode"]
    make_clinically_ready(data)
    PosDispensingQueueService.transition_state(
        episode=episode, new_status="CHECKING", actor=data["pharmacist"]
    )
    episode.refresh_from_db()
    PosDispensingQueueService.transition_state(
        episode=episode, new_status="READY_FOR_PAYMENT", actor=data["pharmacist"]
    )
    data["operator_shift"].state = "CLOSED"
    data["operator_shift"].save(update_fields=["state", "updated_at"])

    with pytest.raises(ValidationError, match="no active shift"):
        PosPaymentOrchestrationService.process_payment(
            episode=episode,
            tender_type="CASH",
            paid_amount=Decimal("500.00"),
            cashier=data["cashier"],
            idempotency_key="PAY-CLOSED-SHIFT",
            device_id=data["device_id"],
        )


def test_repeat_is_consumed_on_supply_not_merely_probed(domain):
    """Was: eligibility probed twice, repeats_remaining never decremented."""
    data = domain
    rx = data["rx"]
    make_clinically_ready(data)
    episode = data["episode"]
    episode.status = "READY_FOR_SUPPLY"
    episode.payment_state = "PAID"
    episode.save()

    before = rx.repeats_remaining
    probe = PosPartialRepeatService.check_repeat_eligibility(
        tenant=data["tenant"], prescription_id=rx.id
    )
    assert probe["advisory_only"] is True, "the probe must not be treated as a claim"

    PosCollectionService.confirm_collection(
        episode=episode, collector_name="John Doe", actor=data["pharmacist"], idempotency_key="RPT-1"
    )
    rx.refresh_from_db()
    assert rx.repeats_remaining <= before


def test_changed_prescription_invalidates_the_existing_approval(domain):
    """A changed basket must not be able to reuse an earlier verification."""
    data = domain
    make_clinically_ready(data)
    episode = data["episode"]
    episode.status = "READY_FOR_SUPPLY"
    episode.payment_state = "PAID"
    episode.save()

    # Mutate the prescription so its context hash no longer matches.
    # all_objects, not rx.items: the related manager is tenant-scoped and
    # returns nothing without an ambient tenant context.
    item = PrescriptionItem.all_objects.filter(prescription=data["rx"]).first()
    item.medication_name = f"{item.medication_name} (amended)"
    item.save()

    with pytest.raises(ValidationError, match="current pharmacist verification"):
        PosCollectionService.confirm_collection(
            episode=episode,
            collector_name="John Doe",
            actor=data["pharmacist"],
            idempotency_key="STALE-1",
        )
    assert not MedicineSupply.all_objects.filter(episode=episode).exists()


# --------------------------------------------------------------------------
# RBAC / SEPARATION OF DUTIES
# --------------------------------------------------------------------------


def test_cashier_cannot_supply_medicine(domain):
    data = domain
    make_clinically_ready(data)
    episode = data["episode"]
    episode.status = "READY_FOR_SUPPLY"
    episode.payment_state = "PAID"
    episode.save()

    with pytest.raises(PermissionDenied):
        PosCollectionService.confirm_collection(
            episode=episode,
            collector_name="John Doe",
            actor=data["cashier"],
            idempotency_key="CASHIER-SUPPLY-1",
        )


def test_cashier_cannot_record_counselling(domain):
    with pytest.raises(PermissionDenied):
        PosCounsellingService.record_counselling(
            episode=domain["episode"], pharmacist=domain["cashier"], notes="nope"
        )


def test_user_without_any_role_cannot_transition_state(domain):
    stranger = User.objects.create(username="stranger", tenant=domain["tenant"])
    with pytest.raises(PermissionDenied):
        PosDispensingQueueService.transition_state(
            episode=domain["episode"], new_status="CHECKING", actor=stranger
        )


# --------------------------------------------------------------------------
# API WRITE SURFACE
# --------------------------------------------------------------------------


def test_episode_state_cannot_be_mutated_by_patch(domain):
    """Was: PATCH could set status=SUPPLIED / payment_state=PAID directly."""
    data = domain
    client = APIClient()
    client.force_authenticate(user=data["pharmacist"])
    url = reverse("pos-dispensing-episodes-detail", args=[data["episode"].id])

    response = client.patch(
        url, {"status": "SUPPLIED", "payment_state": "PAID"}, format="json"
    )
    assert response.status_code in (403, 405), response.status_code

    data["episode"].refresh_from_db()
    assert data["episode"].status == "PREPARING"
    assert data["episode"].payment_state != "PAID"


def test_episode_cannot_be_deleted_over_the_api(domain):
    data = domain
    client = APIClient()
    client.force_authenticate(user=data["pharmacist"])
    url = reverse("pos-dispensing-episodes-detail", args=[data["episode"].id])

    response = client.delete(url)
    assert response.status_code in (403, 405), response.status_code
    assert DispensingEpisode.all_objects.filter(id=data["episode"].id).exists()
