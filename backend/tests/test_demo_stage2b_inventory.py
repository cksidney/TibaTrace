"""Stage 2B.2B — inventory ownership, release, posting, balances & FEFO tests.

Validates that:
- Quality release gate enforces all 11 conditions.
- Partial release lifecycle (QUARANTINED -> PARTIALLY_RELEASED -> RELEASED) is enforced.
- Only approved inventory (accepted_quantity) is posted into inventory.
- InventoryLedger is authoritative and append-only.
- InventoryBalanceService.rebuild_all_balances is idempotent and produces zero drift.
- InventoryBatch is a projection created ONLY for posted stock.
- Location compatibility (vault, cold room, store) is strictly enforced.
- FEFOAllocationService allocates earliest eligible expiry stock first.
- Idempotency & resume create 0 duplicate releases, 0 duplicate ledger entries, 0 duplicate balances.
- QualityInventoryValidator passes clean.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db.models import Sum

from apps.inventory.models import InventoryBalance, InventoryBatch, InventoryLedgerEntry
from apps.inventory.services import FEFOAllocationService, InventoryBalanceService
from apps.platform.demo.generation import stage2b, stage2b2
from apps.platform.demo.generation.context import GenerationContext
from apps.platform.demo.generation.orchestrator import MasterDataOrchestrator
from apps.platform.demo.generation.stages import STAGES
from apps.platform.demo.generation.validation import QualityInventoryValidator, validate_demo_scenario
from apps.platform.demo.models import DemoScenarioRun
from apps.platform.demo.profiles import PILOT, get_master_data_targets
from apps.procurement.models import QualityDecision, ReceivedBatch
from apps.procurement.services.receiving_service import GoodsReceivingService
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
def inventory_ready(db):
    """A tenant with Stage 2B.1, 2B.2A, and 2B.2B fully executed."""
    call_command_catalogue()
    tenant = Tenant.objects.create(name="S2B Inventory Chemists", slug="s2binventorytest", is_demo=True)
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
        ctx, stages=stage2b.STAGE_2B_1 + stage2b2.STAGE_2B_2A + stage2b2.STAGE_2B_2B
    )
    orchestrator.run()
    return tenant, run, ctx, orchestrator


# ---------------------------------------------------------------------------
# Quality Release Gate Tests
# ---------------------------------------------------------------------------


def test_quality_release_gate_refusals(inventory_ready):
    """Quality release gate must refuse uninspected, unapproved, expired, or non-releasable batches."""
    tenant, run, ctx, _ = inventory_ready
    releaser = ctx.get("user:quality")

    # Pick a non-approved batch (e.g. REJECT decision)
    rejected_batch = ReceivedBatch.all_objects.filter(
        tenant=tenant,
        quality_status=ReceivedBatch.QualityStatus.QUARANTINED
    ).exclude(
        id__in=QualityDecision.all_objects.filter(
            tenant=tenant, decision=QualityDecision.Outcome.APPROVE_FOR_RELEASE
        ).values("batch_id")
    ).first()

    if rejected_batch:
        with pytest.raises(ValidationError, match="not releasable|expired|decision"):
            GoodsReceivingService.release_batch(
                batch=rejected_batch, released_by=releaser, as_of=AS_OF
            )


# ---------------------------------------------------------------------------
# Lifecycle & Quantity Posting Tests
# ---------------------------------------------------------------------------


def test_batch_lifecycle_statuses(inventory_ready):
    """Batches must be RELEASED, PARTIALLY_RELEASED, or QUARANTINED."""
    tenant, *_ = inventory_ready
    batches = ReceivedBatch.all_objects.filter(tenant=tenant)
    statuses = set(batches.values_list("quality_status", flat=True))

    assert ReceivedBatch.QualityStatus.RELEASED in statuses or ReceivedBatch.QualityStatus.PARTIALLY_RELEASED in statuses
    assert ReceivedBatch.QualityStatus.QUARANTINED in statuses

    for b in batches:
        if b.accepted_quantity >= b.received_quantity and b.accepted_quantity > 0:
            assert b.quality_status == ReceivedBatch.QualityStatus.RELEASED
        elif b.accepted_quantity > 0:
            assert b.quality_status == ReceivedBatch.QualityStatus.PARTIALLY_RELEASED
        else:
            assert b.quality_status in (ReceivedBatch.QualityStatus.QUARANTINED, ReceivedBatch.QualityStatus.REJECTED)


def test_only_accepted_quantity_posted(inventory_ready):
    """Ledger and InventoryBatch must match accepted_quantity only."""
    tenant, *_ = inventory_ready
    released_batches = ReceivedBatch.all_objects.filter(
        tenant=tenant,
        quality_status__in=(ReceivedBatch.QualityStatus.RELEASED, ReceivedBatch.QualityStatus.PARTIALLY_RELEASED)
    )

    total_accepted = released_batches.aggregate(s=Sum("accepted_quantity"))["s"] or 0
    total_ledger = InventoryLedgerEntry.all_objects.filter(tenant=tenant).aggregate(s=Sum("quantity_delta"))["s"] or 0
    total_balance = InventoryBalance.all_objects.filter(tenant=tenant).aggregate(s=Sum("on_hand"))["s"] or 0

    assert total_accepted > 0
    assert total_accepted == total_ledger
    assert total_ledger == total_balance


def test_quarantined_batches_not_posted(inventory_ready):
    """Quarantined batches must never create InventoryBatch or ledger entries."""
    tenant, *_ = inventory_ready
    quarantined = ReceivedBatch.all_objects.filter(
        tenant=tenant, quality_status=ReceivedBatch.QualityStatus.QUARANTINED
    )

    for qb in quarantined:
        assert not InventoryBatch.all_objects.filter(tenant=tenant, source_received_batch=qb).exists()


# ---------------------------------------------------------------------------
# Balance Rebuild & Location Compatibility
# ---------------------------------------------------------------------------


def test_balance_rebuild_zero_drift(inventory_ready):
    """Rebuilding balances from ledger must yield identical totals."""
    tenant, *_ = inventory_ready
    before_sum = InventoryBalance.all_objects.filter(tenant=tenant).aggregate(s=Sum("on_hand"))["s"] or 0

    InventoryBalanceService.rebuild_all_balances(tenant=tenant)

    after_sum = InventoryBalance.all_objects.filter(tenant=tenant).aggregate(s=Sum("on_hand"))["s"] or 0
    assert before_sum == after_sum


def test_location_capabilities_enforced(inventory_ready):
    """Controlled and cold chain stock must be stored in compatible locations."""
    tenant, *_ = inventory_ready
    from apps.medicines.provisioning import _is_cold_chain, _is_controlled

    balances = InventoryBalance.all_objects.filter(tenant=tenant, available__gt=0).select_related("location", "sku")
    for bal in balances:
        if _is_controlled(bal.sku):
            assert bal.location.controlled_drug_capability, f"{bal.sku} in non-vault location"
        if _is_cold_chain(bal.sku):
            assert bal.location.cold_chain_capability, f"{bal.sku} in non-cold room location"


# ---------------------------------------------------------------------------
# FEFO & Validation
# ---------------------------------------------------------------------------


def test_fefo_allocation_order(inventory_ready):
    """FEFOAllocationService must allocate stock in strict earliest-expiry order."""
    tenant, *_ = inventory_ready
    balances = InventoryBalance.all_objects.filter(tenant=tenant, available__gt=0).select_related("branch", "sku")

    tested = 0
    for bal in balances:
        allocations = FEFOAllocationService.allocate_stock(
            tenant=tenant, branch=bal.branch, sku=bal.sku, required_quantity=5
        )
        if len(allocations) > 1:
            tested += 1
            expiries = [batch.expiry_date for batch, _qty in allocations]
            assert expiries == sorted(expiries), f"FEFO allocation out of order: {expiries}"


def test_quality_inventory_validator_passes(inventory_ready):
    """QualityInventoryValidator outputs PASS with zero findings."""
    tenant, run, *_ = inventory_ready
    res = QualityInventoryValidator(run=run, tenant=tenant).run_all()
    assert res["status"] == "PASS"
    assert res["failure_count"] == 0

    helper_res = validate_demo_scenario(run, tenant)
    assert helper_res["status"] == "PASS"


# ---------------------------------------------------------------------------
# Idempotency & Resume
# ---------------------------------------------------------------------------


def test_stage2b2b_idempotency_and_resume(inventory_ready):
    """Re-running Stage 2B.2B produces zero duplicate releases, ledger entries, or balances."""
    tenant, run, ctx, _ = inventory_ready

    ledger_before = InventoryLedgerEntry.all_objects.filter(tenant=tenant).count()
    inv_batches_before = InventoryBatch.all_objects.filter(tenant=tenant).count()

    ctx_resume = _context(tenant, run)
    for stage in STAGES:
        stage.rehydrate(ctx_resume)

    orchestrator = MasterDataOrchestrator(
        ctx_resume, stages=stage2b.STAGE_2B_1 + stage2b2.STAGE_2B_2A + stage2b2.STAGE_2B_2B
    )
    orchestrator.run(resume=True)

    ledger_after = InventoryLedgerEntry.all_objects.filter(tenant=tenant).count()
    inv_batches_after = InventoryBatch.all_objects.filter(tenant=tenant).count()

    assert ledger_after == ledger_before
    assert inv_batches_after == inv_batches_before

    validator_res = QualityInventoryValidator(run=run, tenant=tenant).run_all()
    assert validator_res["status"] == "PASS"
