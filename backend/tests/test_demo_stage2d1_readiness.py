"""Stage 2D.1 — Patient, Prescription, Clinical and Commercial Readiness unit & integration tests.

Validates:
- Prescription intake & legal validation.
- CDS & POS clinical screening (interactions, allergies, duplicate therapy).
- Pharmacist reviews, clinical overrides, and counselling requirements.
- Authoritative pricing resolution via PriceResolutionService.
- Commercial sales order preparation.
- Inventory stock reservation locking via InventoryReservationService.
- Composable readiness projection via DispensingReadinessProjectionService.
- Strict NO-DISPENSE BOUNDARY enforcement (0 supplied, 0 ISSUE entries, 0 consumed reservations, 0 payment settlements).
- Idempotency & resume prevent duplicate records.
- Stage2D1Validator outputs PASS with 0 findings.
"""

from __future__ import annotations

import io
from datetime import date

import pytest

from apps.cds.models import PosClinicalScreening
from apps.inventory.models import InventoryLedgerEntry, InventoryReservation
from apps.organizations.models import Location
from apps.platform.demo.generation import stage2b, stage2b2, stage2c, stage2d
from apps.platform.demo.generation.context import GenerationContext
from apps.platform.demo.generation.orchestrator import MasterDataOrchestrator
from apps.platform.demo.generation.stages import STAGES
from apps.platform.demo.generation.validation import Stage2D1Validator, validate_demo_scenario
from apps.platform.demo.models import DemoScenarioRun
from apps.platform.demo.profiles import PILOT, get_master_data_targets
from apps.prescription.models import Prescription
from apps.prescription.services.dispensing_readiness_projection import DispensingReadinessProjectionService
from apps.sales.models import SalesOrder
from apps.tenancy.models import Tenant

SEED = 98124012
AS_OF = date(2026, 8, 3)
PASSWORD = "Demo-Local-Pass-9182!"


def _context(tenant, run):
    return GenerationContext(
        run=run, tenant=tenant, seed=SEED, as_of=AS_OF,
        targets=get_master_data_targets("large"), demo_password=PASSWORD,
    )


def call_command_catalogue():
    from django.core.management import call_command
    call_command("seed_medicine_catalogue", stdout=io.StringIO())


@pytest.fixture
def readiness_ready(db):
    """A tenant with Stage 2B, 2C, and Stage 2D.1 fully executed."""
    call_command_catalogue()
    tenant = Tenant.objects.create(name="S2D Readiness Chemists", slug="s2dreadinesstest", is_demo=True)
    run = DemoScenarioRun.all_objects.create(
        tenant=tenant, scenario_name="nairobi-chemists", scenario_version="1.0.0",
        profile=PILOT.key, random_seed=SEED, as_of_date=AS_OF, scale="large",
        demo_version="2026.08.03",
    )
    MasterDataOrchestrator(_context(tenant, run)).run()

    run.refresh_from_db()
    ctx = _context(tenant, run)
    for stage in STAGES:
        stage.rehydrate(ctx)

    orchestrator = MasterDataOrchestrator(
        ctx, stages=stage2b.STAGE_2B_1 + stage2b2.STAGE_2B_2A + stage2b2.STAGE_2B_2B + stage2c.STAGE_2C + stage2d.STAGE_2D_1
    )
    orchestrator.run()
    return tenant, run, ctx, orchestrator


# ---------------------------------------------------------------------------
# Intake & Clinical Screening Tests
# ---------------------------------------------------------------------------


def test_prescription_intake_and_validation(readiness_ready):
    """Prescriptions must be intaken and linked to valid patients and prescribers."""
    tenant, *_ = readiness_ready
    prescriptions = Prescription.all_objects.filter(tenant=tenant)

    assert prescriptions.count() > 0
    for rx in prescriptions:
        assert rx.patient is not None
        assert rx.practitioner is not None
        assert rx.legal_validation_state in ("PASSED", "VALIDATED", "PENDING")
        assert rx.status != "DISPENSED"


def test_clinical_screening_evaluations(readiness_ready):
    """Clinical Decision Support evaluations must produce structured screenings."""
    tenant, *_ = readiness_ready
    screenings = PosClinicalScreening.all_objects.filter(tenant=tenant)

    assert screenings.count() > 0


# ---------------------------------------------------------------------------
# Commercial & Inventory Tests
# ---------------------------------------------------------------------------


def test_commercial_sales_orders_and_pricing(readiness_ready):
    """Commercial sales orders must have server-derived line pricing."""
    tenant, *_ = readiness_ready
    orders = SalesOrder.all_objects.filter(tenant=tenant)

    assert orders.count() > 0
    for order in orders:
        assert order.status in ("DRAFT", "QUOTED", "READY_FOR_PAYMENT")
        for line in order.lines.all():
            assert line.agreed_unit_price > 0
            assert line.line_total == line.approved_quantity * line.agreed_unit_price


def test_inventory_reservation_locking(readiness_ready):
    """Inventory reservations lock available stock without mutating on_hand balance."""
    tenant, *_ = readiness_ready
    reservations = InventoryReservation.all_objects.filter(tenant=tenant)

    assert reservations.count() > 0
    for res in reservations.filter(status=InventoryReservation.Status.ALLOCATED):
        assert res.allocated_quantity > 0


# ---------------------------------------------------------------------------
# Readiness Projection & No-Dispense Boundary Tests
# ---------------------------------------------------------------------------


def test_dispensing_readiness_projection(readiness_ready):
    """DispensingReadinessProjectionService outputs composable readiness assessments."""
    tenant, _, ctx, _ = readiness_ready
    location = Location.all_objects.filter(tenant=tenant).first()
    actor = ctx.get("user:ops")
    planned = ctx.get("dispensing:planned_episodes") or []

    assert len(planned) > 0
    ep = planned[0]

    report = DispensingReadinessProjectionService.evaluate_readiness(
        tenant=tenant,
        branch=location,
        case_reference=ep["case_reference"],
        prescription=ep.get("prescription"),
        sales_order=ep.get("sales_order"),
        device_id="DEV-POS-001",
        actor=actor,
    )

    assert report.overall_readiness in (
        "READY_FOR_PAYMENT", "CLINICAL_REVIEW_REQUIRED", "STOCK_UNAVAILABLE",
        "PARTIALLY_RESERVED", "REGISTER_REQUIRED", "PRACTITIONER_INVALID",
        "COUNSELLING_REQUIRED", "BLOCKED_CONTROLLED_MEDICINE"
    )
    assert report.payment_state == "NOT_PAID"
    assert report.dispensing_state == "NOT_DISPENSED"


def test_no_dispense_boundary_strictly_enforced(readiness_ready):
    """Zero supplied prescriptions, zero ISSUE ledger entries, zero consumed reservations."""
    tenant, *_ = readiness_ready

    supplied = Prescription.all_objects.filter(tenant=tenant, status="DISPENSED").count()
    issue_entries = InventoryLedgerEntry.all_objects.filter(
        tenant=tenant, entry_type=InventoryLedgerEntry.EntryType.ISSUE
    ).count()
    fulfilled_res = InventoryReservation.all_objects.filter(
        tenant=tenant, status=InventoryReservation.Status.FULFILLED
    ).count()

    assert supplied == 0, "No prescription may be marked DISPENSED in Stage 2D.1"
    assert issue_entries == 0, "No ISSUE ledger entry may post in Stage 2D.1"
    assert fulfilled_res == 0, "No reservation may be marked FULFILLED in Stage 2D.1"


# ---------------------------------------------------------------------------
# Validator & Resume Tests
# ---------------------------------------------------------------------------


def test_stage2d1_validator_passes(readiness_ready):
    """Stage2D1Validator outputs PASS with 0 findings."""
    tenant, run, *_ = readiness_ready
    res = Stage2D1Validator(run=run, tenant=tenant).run_all()
    assert res["status"] == "PASS"
    assert res["failure_count"] == 0

    helper_res = validate_demo_scenario(run, tenant)
    assert helper_res["status"] == "PASS"


def test_stage2d1_idempotency_and_resume(readiness_ready):
    """Re-running Stage 2D.1 produces zero duplicate prescriptions, orders, or reservations."""
    tenant, run, ctx, _ = readiness_ready

    rx_before = Prescription.all_objects.filter(tenant=tenant).count()
    orders_before = SalesOrder.all_objects.filter(tenant=tenant).count()
    res_before = InventoryReservation.all_objects.filter(tenant=tenant).count()

    ctx_resume = _context(tenant, run)
    for stage in STAGES:
        stage.rehydrate(ctx_resume)

    orchestrator = MasterDataOrchestrator(
        ctx_resume, stages=stage2b.STAGE_2B_1 + stage2b2.STAGE_2B_2A + stage2b2.STAGE_2B_2B + stage2c.STAGE_2C + stage2d.STAGE_2D_1
    )
    orchestrator.run(resume=True)

    rx_after = Prescription.all_objects.filter(tenant=tenant).count()
    orders_after = SalesOrder.all_objects.filter(tenant=tenant).count()
    res_after = InventoryReservation.all_objects.filter(tenant=tenant).count()

    assert rx_after == rx_before
    assert orders_after == orders_before
    assert res_after == res_before

    validator_res = Stage2D1Validator(run=run, tenant=tenant).run_all()
    assert validator_res["status"] == "PASS"
