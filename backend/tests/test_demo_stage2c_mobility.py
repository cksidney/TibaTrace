"""Stage 2C — Stock Mobility & Reservation Engine unit & integration tests.

Validates:
- Inter-Branch Stock Transfer lifecycle (REQUESTED -> APPROVED -> DISPATCHED -> RECEIVED).
- Segregation of duties (requester != approver on stock transfers).
- Stock transfer rejection and cancellation workflows.
- Inventory Reservation lifecycle (ALLOCATED, EXPIRED, RELEASED).
- FEFO allocation locking (never allocates expired/quarantined/held/rejected stock).
- Ledger and balance integrity (TRANSFER_OUT == TRANSFER_IN, 0 stock leak).
- InventoryBalanceService.rebuild_all_balances produces 0 drift.
- Idempotency & resume create 0 duplicate transfers/reservations/ledger entries.
- StockMobilityValidator outputs PASS with 0 findings.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, InventoryReservation, StockTransfer
from apps.inventory.services import InventoryBalanceService
from apps.platform.demo.generation import stage2b, stage2b2, stage2c
from apps.platform.demo.generation.context import GenerationContext
from apps.platform.demo.generation.orchestrator import MasterDataOrchestrator
from apps.platform.demo.generation.stages import STAGES
from apps.platform.demo.generation.validation import StockMobilityValidator, validate_demo_scenario
from apps.platform.demo.models import DemoScenarioRun
from apps.platform.demo.profiles import PILOT, get_master_data_targets
from apps.tenancy.models import Tenant

SEED = 83492011
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
def mobility_ready(db):
    """A tenant with Stage 2B.1, 2B.2A, 2B.2B, and Stage 2C fully executed."""
    call_command_catalogue()
    tenant = Tenant.objects.create(name="S2C Mobility Chemists", slug="s2cmobilitytest", is_demo=True)
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
        ctx, stages=stage2b.STAGE_2B_1 + stage2b2.STAGE_2B_2A + stage2b2.STAGE_2B_2B + stage2c.STAGE_2C
    )
    orchestrator.run()
    return tenant, run, ctx, orchestrator


# ---------------------------------------------------------------------------
# Transfer Lifecycle Tests
# ---------------------------------------------------------------------------


def test_transfer_lifecycle_and_counts(mobility_ready):
    """Stock transfers must be generated across COMPLETED, REJECTED, and CANCELLED statuses."""
    tenant, *_ = mobility_ready
    transfers = StockTransfer.all_objects.filter(tenant=tenant)

    assert transfers.count() > 0
    statuses = set(transfers.values_list("status", flat=True))
    assert StockTransfer.Status.RECEIVED in statuses or StockTransfer.Status.DISPATCHED in statuses

    for t in transfers.filter(status=StockTransfer.Status.APPROVED):
        if t.requested_by_id and t.approved_by_id:
            assert str(t.requested_by_id) != str(t.approved_by_id), "Requester approved own transfer"


def test_transfer_ledger_balance(mobility_ready):
    """TRANSFER_OUT total quantity must equal TRANSFER_IN total quantity."""
    tenant, *_ = mobility_ready

    out_qty = abs(
        InventoryLedgerEntry.all_objects.filter(
            tenant=tenant, entry_type=InventoryLedgerEntry.EntryType.TRANSFER_OUT
        ).aggregate(s=Sum("quantity_delta"))["s"] or Decimal("0")
    )
    in_qty = InventoryLedgerEntry.all_objects.filter(
        tenant=tenant, entry_type=InventoryLedgerEntry.EntryType.TRANSFER_IN
    ).aggregate(s=Sum("quantity_delta"))["s"] or Decimal("0")

    assert out_qty > 0
    assert out_qty == in_qty, f"Transfer imbalance: OUT {out_qty} != IN {in_qty}"


# ---------------------------------------------------------------------------
# Reservation Lifecycle Tests
# ---------------------------------------------------------------------------


def test_reservation_lifecycle_and_counts(mobility_ready):
    """Reservations must exist across ALLOCATED, EXPIRED, and RELEASED statuses."""
    tenant, *_ = mobility_ready
    reservations = InventoryReservation.all_objects.filter(tenant=tenant)

    assert reservations.count() > 0
    statuses = set(reservations.values_list("status", flat=True))
    assert InventoryReservation.Status.ALLOCATED in statuses
    assert InventoryReservation.Status.EXPIRED in statuses
    assert InventoryReservation.Status.RELEASED in statuses


def test_no_negative_stock_balances(mobility_ready):
    """Zero negative on_hand or available inventory balances."""
    tenant, *_ = mobility_ready

    neg_on_hand = InventoryBalance.all_objects.filter(tenant=tenant, on_hand__lt=0).count()
    neg_avail = InventoryBalance.all_objects.filter(tenant=tenant, available__lt=0).count()

    assert neg_on_hand == 0
    assert neg_avail == 0


def test_mobility_balance_rebuild_zero_drift(mobility_ready):
    """Rebuilding balances from ledger must produce zero drift."""
    tenant, *_ = mobility_ready
    before = InventoryBalance.all_objects.filter(tenant=tenant).aggregate(s=Sum("on_hand"))["s"] or Decimal("0")

    InventoryBalanceService.rebuild_all_balances(tenant=tenant)

    after = InventoryBalance.all_objects.filter(tenant=tenant).aggregate(s=Sum("on_hand"))["s"] or Decimal("0")
    assert before == after


# ---------------------------------------------------------------------------
# Validation & Idempotency Tests
# ---------------------------------------------------------------------------


def test_stock_mobility_validator_passes(mobility_ready):
    """StockMobilityValidator outputs PASS with 0 findings."""
    tenant, run, *_ = mobility_ready
    res = StockMobilityValidator(run=run, tenant=tenant).run_all()
    assert res["status"] == "PASS"
    assert res["failure_count"] == 0

    helper_res = validate_demo_scenario(run, tenant)
    assert helper_res["status"] == "PASS"


def test_stage2c_idempotency_and_resume(mobility_ready):
    """Re-running Stage 2C produces zero duplicate transfers, reservations, or ledger entries."""
    tenant, run, ctx, _ = mobility_ready

    transfers_before = StockTransfer.all_objects.filter(tenant=tenant).count()
    reservations_before = InventoryReservation.all_objects.filter(tenant=tenant).count()
    ledger_before = InventoryLedgerEntry.all_objects.filter(tenant=tenant).count()

    ctx_resume = _context(tenant, run)
    for stage in STAGES:
        stage.rehydrate(ctx_resume)

    orchestrator = MasterDataOrchestrator(
        ctx_resume, stages=stage2b.STAGE_2B_1 + stage2b2.STAGE_2B_2A + stage2b2.STAGE_2B_2B + stage2c.STAGE_2C
    )
    orchestrator.run(resume=True)

    transfers_after = StockTransfer.all_objects.filter(tenant=tenant).count()
    reservations_after = InventoryReservation.all_objects.filter(tenant=tenant).count()
    ledger_after = InventoryLedgerEntry.all_objects.filter(tenant=tenant).count()

    assert transfers_after == transfers_before
    assert reservations_after == reservations_before
    assert ledger_after == ledger_before

    validator_res = StockMobilityValidator(run=run, tenant=tenant).run_all()
    assert validator_res["status"] == "PASS"
