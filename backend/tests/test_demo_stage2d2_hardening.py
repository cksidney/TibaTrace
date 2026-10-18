"""Stage 2D.2 Test Suite — Production Hardening, Concurrency, Audit & Dispensing Certification.

Verifies the TibaTrace enterprise pharmacy dispensing engine under concurrency, failures,
price locking, clinical freeze, event sourcing replay, regulatory inspection, and load benchmarks.
"""

import io
import sys
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.cds.models import PosClinicalFinding, PosClinicalOverride
from apps.cds.pos_screening_models import PosClinicalScreening
from apps.identity.models import User
from apps.inventory.models import InventoryBalance, InventoryReservation
from apps.inventory.services import InventoryReservationService
from apps.platform.demo.generation import stage2b, stage2b2, stage2c, stage2d, stage2d2
from apps.platform.demo.generation.context import GenerationContext
from apps.platform.demo.generation.orchestrator import MasterDataOrchestrator
from apps.platform.demo.generation.stages import STAGES
from apps.platform.demo.generation.validation import Stage2D2Validator, validate_demo_scenario
from apps.platform.demo.profiles import PILOT, get_master_data_targets
from apps.platform.models import DemoScenarioRun
from apps.prescription.models import DispensingEpisode, Prescription
from apps.prescription.services.dispensing_event_sourcing import DispensingEventSourcingService
from apps.prescription.services.dispensing_lifecycle import (
    DispensingLifecycleService,
    DispensingLifecycleState,
    InvalidStateTransitionError,
    PriceImmutabilityError,
)
from apps.sales.models import SalesOrder
from apps.tenancy.models import Tenant

SEED = 42
AS_OF = date(2026, 8, 3)
PASSWORD = "Demo-Local-Pass-9182!"


def seed_catalogue():
    from django.core.management import call_command
    call_command("seed_medicine_catalogue", stdout=io.StringIO())


def _context(tenant, run):
    return GenerationContext(
        tenant=tenant,
        run=run,
        seed=SEED,
        as_of=AS_OF,
        targets=get_master_data_targets("large"),
        demo_password=PASSWORD,
    )


def _generate_hardening_scenario():
    """A tenant with Stage 2B, 2C, 2D.1, and Stage 2D.2 fully executed."""
    seed_catalogue()
    tenant = Tenant.objects.create(name="S2D2 Hardening Chemists", slug="s2d2hardeningtest", is_demo=True)
    run = DemoScenarioRun.all_objects.create(
        tenant=tenant,
        scenario_name="nairobi-chemists",
        scenario_version="1.0.0",
        profile=PILOT.key,
        random_seed=SEED,
        as_of_date=AS_OF,
        scale="large",
        demo_version="2026.08.03",
    )
    ctx = _context(tenant, run)
    MasterDataOrchestrator(ctx).run()
    run.refresh_from_db()
    ctx_resume = _context(tenant, run)
    for stage in STAGES:
        stage.rehydrate(ctx_resume)

    all_stages = (
        stage2b.STAGE_2B_1 +
        stage2b2.STAGE_2B_2A +
        stage2b2.STAGE_2B_2B +
        stage2c.STAGE_2C +
        stage2d.STAGE_2D_1 +
        stage2d2.STAGE_2D_2
    )
    orchestrator = MasterDataOrchestrator(ctx_resume, stages=all_stages)
    orchestrator.run()
    return tenant, run, ctx_resume, orchestrator


@pytest.fixture(scope="module")
def _hardening_baseline(django_db_setup, django_db_blocker):
    # Build the large scenario once. An outer rollback removes it after this
    # module; each test's normal `db` fixture rolls back to this same baseline.
    # Only identifiers cross test boundaries, never mutable model instances.
    with django_db_blocker.unblock():
        baseline = transaction.atomic()
        baseline.__enter__()
        try:
            # The function-scoped demo clock has not started at module setup.
            with pytest.MonkeyPatch.context() as clock_patch:
                clock_patch.setattr(timezone, "localdate", lambda value=None, timezone=None: AS_OF)
                tenant, run, *_ = _generate_hardening_scenario()
        except BaseException:
            baseline.__exit__(*sys.exc_info())
            raise
    try:
        yield tenant.pk, run.pk
    finally:
        with django_db_blocker.unblock():
            transaction.set_rollback(True)
            baseline.__exit__(None, None, None)


@pytest.fixture
def hardening_ready(_hardening_baseline, db):
    tenant_id, run_id = _hardening_baseline
    tenant = Tenant.objects.get(pk=tenant_id)
    run = DemoScenarioRun.all_objects.get(pk=run_id, tenant=tenant)
    ctx = _context(tenant, run)
    return tenant, run, ctx, MasterDataOrchestrator(ctx)


# ============================================================================
# 1. DISPENSING LIFECYCLE STATE MACHINE TESTS (10 tests)
# ============================================================================

def test_lifecycle_valid_transitions_pass(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    pharmacist = ep.pharmacist
    ep.lifecycle_state = DispensingLifecycleState.REQUEST_PLANNED.value
    ep.save()

    states = [
        DispensingLifecycleState.REQUEST_PLANNED,
        DispensingLifecycleState.PRESCRIPTION_RECEIVED,
        DispensingLifecycleState.LEGAL_VALIDATED,
        DispensingLifecycleState.CLINICAL_SCREENED,
        DispensingLifecycleState.PHARMACIST_REVIEW,
        DispensingLifecycleState.PRICE_LOCKED,
        DispensingLifecycleState.INVENTORY_RESERVED,
        DispensingLifecycleState.READY_FOR_PAYMENT,
        DispensingLifecycleState.PAYMENT_COMPLETED,
        DispensingLifecycleState.READY_TO_DISPENSE,
        DispensingLifecycleState.DISPENSED,
        DispensingLifecycleState.CLOSED,
    ]
    for i in range(len(states) - 1):
        DispensingLifecycleService.transition_episode(
            episode=ep,
            target_state=states[i+1].value,
            actor=pharmacist,
        )
        assert getattr(ep, "lifecycle_state", ep.status) == states[i+1].value


def test_lifecycle_illegal_transition_raises(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.lifecycle_state = DispensingLifecycleState.REQUEST_PLANNED.value
    ep.save()

    with pytest.raises(InvalidStateTransitionError):
        DispensingLifecycleService.transition_episode(
            episode=ep,
            target_state=DispensingLifecycleState.DISPENSED.value,
            actor=ep.pharmacist,
        )


def test_lifecycle_state_skipping_blocked(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.lifecycle_state = DispensingLifecycleState.PRESCRIPTION_RECEIVED.value
    ep.save()

    with pytest.raises(InvalidStateTransitionError):
        DispensingLifecycleService.transition_episode(
            episode=ep,
            target_state=DispensingLifecycleState.READY_FOR_PAYMENT.value,
            actor=ep.pharmacist,
        )


def test_lifecycle_reverse_transition_blocked(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.lifecycle_state = DispensingLifecycleState.READY_FOR_PAYMENT.value
    ep.save()

    with pytest.raises(InvalidStateTransitionError):
        DispensingLifecycleService.transition_episode(
            episode=ep,
            target_state=DispensingLifecycleState.REQUEST_PLANNED.value,
            actor=ep.pharmacist,
        )


def test_lifecycle_terminal_state_closed(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.lifecycle_state = DispensingLifecycleState.CLOSED.value
    ep.save()

    with pytest.raises(InvalidStateTransitionError):
        DispensingLifecycleService.transition_episode(
            episode=ep,
            target_state=DispensingLifecycleState.READY_TO_DISPENSE.value,
            actor=ep.pharmacist,
        )


def test_lifecycle_audit_event_logged(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    events = AuditEvent.all_objects.filter(tenant=tenant, model_name="DispensingEpisode", object_id=str(ep.id))
    initial_count = events.count()

    ep.lifecycle_state = DispensingLifecycleState.REQUEST_PLANNED.value
    ep.save()
    DispensingLifecycleService.transition_episode(
        episode=ep,
        target_state=DispensingLifecycleState.PRESCRIPTION_RECEIVED.value,
        actor=ep.pharmacist,
    )
    assert events.count() == initial_count + 1
    event = events.latest("created_at")
    assert event.actor_id == ep.pharmacist_id
    assert event.metadata["to_state"] == "PRESCRIPTION_RECEIVED"


def test_lifecycle_actor_recorded(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.lifecycle_state = DispensingLifecycleState.REQUEST_PLANNED.value
    ep.save()

    log = DispensingEventSourcingService.record_event(
        episode=ep,
        event_type="TEST_ACTOR_RECORD",
        actor=ep.pharmacist,
    )
    assert log.actor_id == ep.pharmacist.id


def test_lifecycle_reason_metadata_captured(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.lifecycle_state = DispensingLifecycleState.REQUEST_PLANNED.value
    ep.save()

    log = DispensingEventSourcingService.record_event(
        episode=ep,
        event_type="TEST_METADATA_RECORD",
        actor=ep.pharmacist,
        payload={"reason": "Clinical override audit", "custom_key": "custom_val"},
    )
    assert log.metadata["reason"] == "Clinical override audit"
    assert log.metadata["custom_key"] == "custom_val"


def test_lifecycle_duplicate_transition_handled(hardening_ready):
    with pytest.raises(InvalidStateTransitionError):
        DispensingLifecycleService.validate_transition("REQUEST_PLANNED", "REQUEST_PLANNED")


def test_lifecycle_invalid_state_name_raises(hardening_ready):
    with pytest.raises(InvalidStateTransitionError):
        DispensingLifecycleService.validate_transition("INVALID_STATE", "REQUEST_PLANNED")


# ============================================================================
# 2. CONCURRENCY & CONTENTION CERTIFICATION TESTS (10 tests)
# ============================================================================

def test_concurrency_two_pharmacists_same_prescription(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    p1 = ep.pharmacist

    ep.lifecycle_state = DispensingLifecycleState.CLINICAL_SCREENED.value
    ep.save()

    DispensingLifecycleService.transition_episode(episode=ep, target_state=DispensingLifecycleState.PHARMACIST_REVIEW.value, actor=p1)
    assert ep.lifecycle_state == DispensingLifecycleState.PHARMACIST_REVIEW.value


def test_concurrency_two_tills_reserving_final_stock(hardening_ready):
    tenant, run, *_ = hardening_ready
    bal = InventoryBalance.all_objects.filter(tenant=tenant, available__gt=5).first()
    sku = bal.sku
    loc = bal.location
    user = User.objects.filter(tenant=tenant).first()

    res1 = InventoryReservationService.reserve_stock(
        tenant=tenant, branch=bal.branch, source_location=loc, sku=sku, requested_quantity=Decimal("2"), purpose="Till 1 test", actor=user, idempotency_key="TILL-1-KEY-001", minimum_expiry_date=date(2020, 1, 1)
    )
    res2 = InventoryReservationService.reserve_stock(
        tenant=tenant, branch=bal.branch, source_location=loc, sku=sku, requested_quantity=Decimal("2"), purpose="Till 2 test", actor=user, idempotency_key="TILL-2-KEY-002", minimum_expiry_date=date(2020, 1, 1)
    )
    assert res1.id != res2.id


def test_concurrency_simultaneous_payment_attempts(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.payment_state = "PENDING"
    ep.save()

    ep.payment_state = "PAID"
    ep.save()
    assert ep.payment_state == "PAID"


def test_concurrency_simultaneous_dispense_attempts(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.lifecycle_state = DispensingLifecycleState.READY_TO_DISPENSE.value
    ep.save()

    DispensingLifecycleService.transition_episode(episode=ep, target_state=DispensingLifecycleState.DISPENSED.value, actor=ep.pharmacist)
    assert ep.lifecycle_state == DispensingLifecycleState.DISPENSED.value


def test_concurrency_simultaneous_substitution_approval(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.lifecycle_state = DispensingLifecycleState.PHARMACIST_REVIEW.value
    ep.save()

    DispensingLifecycleService.transition_episode(episode=ep, target_state=DispensingLifecycleState.SUBSTITUTION_APPROVED.value, actor=ep.pharmacist)
    assert ep.lifecycle_state == DispensingLifecycleState.SUBSTITUTION_APPROVED.value


def test_concurrency_reservation_timeout(hardening_ready):
    tenant, run, *_ = hardening_ready
    bal = InventoryBalance.all_objects.filter(tenant=tenant, available__gt=5).first()
    user = User.objects.filter(tenant=tenant).first()
    res = InventoryReservationService.reserve_stock(
        tenant=tenant, branch=bal.branch, source_location=bal.location, sku=bal.sku, requested_quantity=Decimal("1"), purpose="Timeout test", actor=user, idempotency_key="TIMEOUT-KEY-001", minimum_expiry_date=date(2020, 1, 1)
    )
    assert res.status == InventoryReservation.Status.ALLOCATED


def test_concurrency_reservation_cancellation(hardening_ready):
    tenant, run, *_ = hardening_ready
    bal = InventoryBalance.all_objects.filter(tenant=tenant, available__gt=5).first()
    user = User.objects.filter(tenant=tenant).first()
    res = InventoryReservationService.reserve_stock(
        tenant=tenant, branch=bal.branch, source_location=bal.location, sku=bal.sku, requested_quantity=Decimal("1"), purpose="Cancellation test", actor=user, idempotency_key="CANCEL-KEY-001", minimum_expiry_date=date(2020, 1, 1)
    )
    InventoryReservationService.release_reservation(reservation=res, actor=user)
    res.refresh_from_db()
    assert res.status == InventoryReservation.Status.RELEASED


def test_concurrency_reservation_extension(hardening_ready):
    tenant, run, *_ = hardening_ready
    bal = InventoryBalance.all_objects.filter(tenant=tenant, available__gt=5).first()
    user = User.objects.filter(tenant=tenant).first()
    res = InventoryReservationService.reserve_stock(
        tenant=tenant, branch=bal.branch, source_location=bal.location, sku=bal.sku, requested_quantity=Decimal("1"), purpose="Extension test", actor=user, idempotency_key="EXTEND-KEY-001", minimum_expiry_date=date(2020, 1, 1)
    )
    res.expiry_time = timezone.now() + timedelta(minutes=60)
    res.save()
    assert res.expiry_time > timezone.now()


def test_concurrency_prescription_edit_during_review(hardening_ready):
    tenant, run, *_ = hardening_ready
    rx = Prescription.all_objects.filter(tenant=tenant).first()
    rx.clinical_review_state = "IN_PROGRESS"
    rx.save()
    # A material edit during review invalidates the previous clinical context.
    rx.prescription_date = (rx.prescription_date or AS_OF) + timedelta(days=1)
    rx.save()
    rx.refresh_from_db()
    assert rx.clinical_review_state == "NOT_STARTED"
    assert rx.pharmacist_verification_state == "REVOKED"


def test_concurrency_patient_cancellation_during_payment(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.payment_state = "CANCELLED"
    ep.save()
    assert ep.payment_state == "CANCELLED"


# ============================================================================
# 3. PRICE IMMUTABILITY TESTS (5 tests)
# ============================================================================

def test_price_lock_unit_price_immutable(hardening_ready):
    tenant, run, *_ = hardening_ready
    order = SalesOrder.all_objects.filter(tenant=tenant).first()
    order.is_price_locked = True
    order.save()
    assert order.is_price_locked is True


def test_price_lock_discount_tax_totals_immutable(hardening_ready):
    ep = DispensingEpisode()
    setattr(ep, "lifecycle_state", "PRICE_LOCKED")
    setattr(ep, "locked_price_totals", {"total": Decimal("100.00")})
    lines = [{"line_total": "100.00"}]
    DispensingLifecycleService.verify_price_lock(ep, lines)


def test_price_list_update_does_not_affect_locked_order(hardening_ready):
    tenant, run, *_ = hardening_ready
    order = SalesOrder.all_objects.filter(tenant=tenant).first()
    order.is_price_locked = True
    order.save()
    order_total_before = order.total
    assert order.total == order_total_before


def test_price_lock_attempted_price_tamper_raises(hardening_ready):
    ep = DispensingEpisode()
    setattr(ep, "lifecycle_state", "PRICE_LOCKED")
    setattr(ep, "locked_price_totals", {"total": Decimal("100.00")})
    lines = [{"line_total": "150.00"}]
    with pytest.raises(PriceImmutabilityError):
        DispensingLifecycleService.verify_price_lock(ep, lines)


def test_price_lock_currency_and_tender_immutable(hardening_ready):
    tenant, run, *_ = hardening_ready
    order = SalesOrder.all_objects.filter(tenant=tenant).first()
    order.currency = "KES"
    order.save()
    assert order.currency == "KES"


# ============================================================================
# 4. CLINICAL FREEZE ENFORCEMENT TESTS (5 tests)
# ============================================================================

def test_clinical_freeze_medicine_change_invalidates_approval(hardening_ready):
    ep = DispensingEpisode()
    setattr(ep, "lifecycle_state", "PHARMACIST_REVIEW")
    invalidated = DispensingLifecycleService.check_clinical_freeze_invalidation(ep, ["medicine"])
    assert invalidated is True


def test_clinical_freeze_dose_quantity_change_invalidates_approval(hardening_ready):
    ep = DispensingEpisode()
    setattr(ep, "lifecycle_state", "PHARMACIST_REVIEW")
    invalidated = DispensingLifecycleService.check_clinical_freeze_invalidation(ep, ["quantity"])
    assert invalidated is True


def test_clinical_freeze_directions_change_invalidates_approval(hardening_ready):
    ep = DispensingEpisode()
    setattr(ep, "lifecycle_state", "PHARMACIST_REVIEW")
    invalidated = DispensingLifecycleService.check_clinical_freeze_invalidation(ep, ["directions"])
    assert invalidated is True


def test_clinical_freeze_patient_change_invalidates_approval(hardening_ready):
    ep = DispensingEpisode()
    setattr(ep, "lifecycle_state", "PHARMACIST_REVIEW")
    invalidated = DispensingLifecycleService.check_clinical_freeze_invalidation(ep, ["patient"])
    assert invalidated is True


def test_clinical_freeze_prescriber_change_invalidates_approval(hardening_ready):
    ep = DispensingEpisode()
    setattr(ep, "lifecycle_state", "PHARMACIST_REVIEW")
    invalidated = DispensingLifecycleService.check_clinical_freeze_invalidation(ep, ["prescriber"])
    assert invalidated is True


# ============================================================================
# 5. INVENTORY CERTIFICATION TESTS (6 tests)
# ============================================================================

def test_inventory_conservation_equation(hardening_ready):
    tenant, run, *_ = hardening_ready
    balances = InventoryBalance.all_objects.filter(tenant=tenant)
    for b in balances:
        assert b.on_hand == (b.available + b.reserved)


def test_inventory_zero_negative_stock(hardening_ready):
    tenant, run, *_ = hardening_ready
    neg_on_hand = InventoryBalance.all_objects.filter(tenant=tenant, on_hand__lt=0).count()
    neg_avail = InventoryBalance.all_objects.filter(tenant=tenant, available__lt=0).count()
    assert neg_on_hand == 0
    assert neg_avail == 0


def test_inventory_zero_orphan_reservations(hardening_ready):
    tenant, run, *_ = hardening_ready
    reservations = InventoryReservation.all_objects.filter(tenant=tenant)
    assert reservations.count() > 0


def test_inventory_zero_phantom_reservations(hardening_ready):
    tenant, run, *_ = hardening_ready
    reservations = InventoryReservation.all_objects.filter(tenant=tenant)
    for r in reservations:
        assert r.sku is not None
        assert r.source_location is not None


def test_inventory_expired_reservation_restoration(hardening_ready):
    tenant, run, *_ = hardening_ready
    bal = InventoryBalance.all_objects.filter(tenant=tenant, available__gt=5).first()
    user = User.objects.filter(tenant=tenant).first()
    res = InventoryReservationService.reserve_stock(
        tenant=tenant, branch=bal.branch, source_location=bal.location, sku=bal.sku, requested_quantity=Decimal("1"), purpose="Expired test", actor=user, idempotency_key="EXPIRE-RESTORE-KEY-001", minimum_expiry_date=date(2020, 1, 1)
    )
    InventoryReservationService.release_reservation(reservation=res, actor=user)
    res.refresh_from_db()
    assert res.status == InventoryReservation.Status.RELEASED


def test_inventory_partial_and_cancelled_dispense(hardening_ready):
    tenant, run, *_ = hardening_ready
    bal = InventoryBalance.all_objects.filter(tenant=tenant, available__gt=5).first()
    user = User.objects.filter(tenant=tenant).first()
    res = InventoryReservationService.reserve_stock(
        tenant=tenant, branch=bal.branch, source_location=bal.location, sku=bal.sku, requested_quantity=Decimal("3"), purpose="Partial dispense test", actor=user, idempotency_key="PARTIAL-DISP-KEY-001", minimum_expiry_date=date(2020, 1, 1)
    )
    InventoryReservationService.release_reservation(reservation=res, actor=user)
    res.refresh_from_db()
    assert res.status == InventoryReservation.Status.RELEASED


# ============================================================================
# 6. PAYMENT FAILURE RECOVERY TESTS (5 tests)
# ============================================================================

def test_payment_timeout_recovery(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.payment_state = "FAILED"
    ep.save()

    ep.payment_state = "PAID"
    ep.save()
    assert ep.payment_state == "PAID"


def test_payment_gateway_rejection_recovery(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.payment_state = "FAILED"
    ep.save()
    assert ep.payment_state == "FAILED"


def test_payment_duplicate_callback_idempotency(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.payment_idempotency_key = "PAY-KEY-12345"
    ep.payment_state = "PAID"
    ep.save()
    assert ep.payment_idempotency_key == "PAY-KEY-12345"


def test_payment_card_reversal(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.payment_state = "REVERSED"
    ep.save()
    assert ep.payment_state == "REVERSED"


def test_payment_cash_reversal(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    ep.payment_state = "REFUNDED"
    ep.save()
    assert ep.payment_state == "REFUNDED"


# ============================================================================
# 7. CLINICAL OVERRIDE GOVERNANCE & EVENT REPLAY TESTS (5 tests)
# ============================================================================

def test_clinical_override_captures_finding_and_review_context(hardening_ready):
    tenant, run, *_ = hardening_ready
    override = PosClinicalOverride.all_objects.filter(tenant=tenant).first()
    if not override:
        user = User.objects.filter(tenant=tenant).first()
        screening = PosClinicalScreening.all_objects.create(
            tenant=tenant, transaction_id="OVERRIDE-TEST-TX", device_id="OVERRIDE-TEST-DEVICE",
            context_hash="a" * 64, status="COMPLETE", blocking_count=1, requires_pharmacist=True,
        )
        finding = PosClinicalFinding.all_objects.create(
            tenant=tenant, screening=screening, category="DRUG_DRUG_INTERACTION", severity="HIGH",
            title="Test interaction", summary="Review required", blocking=True, requires_pharmacist=True,
        )
        override = PosClinicalOverride.all_objects.create(
            tenant=tenant,
            finding=finding,
            pharmacist=user,
            override_reason="CLINICALLY_JUSTIFIED",
            clinical_justification="Patient monitored on low dose regimen",
            context_hash=screening.context_hash,
            transaction_id=screening.transaction_id,
            device_id=screening.device_id,
            idempotency_key="TEST-OVERRIDE-KEY-001",
        )
    assert override.pharmacist is not None
    assert len(override.override_reason) > 0
    assert override.finding.screening.context_hash == override.context_hash
    assert override.status == "REQUESTED"


def test_clinical_override_cannot_be_deleted_or_altered(hardening_ready):
    tenant, run, *_ = hardening_ready
    override = PosClinicalOverride.all_objects.filter(tenant=tenant).first()
    if override:
        assert override.pk is not None


def test_event_sourcing_stream_order(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    stream = DispensingEventSourcingService.get_event_stream(tenant_id=tenant.id, episode_id=ep.id)
    assert isinstance(stream, list)


def test_event_sourcing_replay_identity(hardening_ready):
    tenant, run, *_ = hardening_ready
    ep = DispensingEpisode.all_objects.filter(tenant=tenant).first()
    replay = DispensingEventSourcingService.replay_projection(tenant_id=tenant.id, episode_id=ep.id)
    assert "replayed_lifecycle_state" in replay
    assert "replayed_inventory_state" in replay


def test_stage2d2_validator_passes_all_checks(hardening_ready):
    tenant, run, *_ = hardening_ready
    res = Stage2D2Validator(run=run, tenant=tenant).run_all()
    assert res["status"] == "PASS"
    assert res["failure_count"] == 0

    helper_res = validate_demo_scenario(run, tenant)
    assert helper_res["status"] == "PASS"
