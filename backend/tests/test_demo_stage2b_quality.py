"""Stage 2B.2A — quality inspection and quality decisions tests.

Validates that:
- Every scenario-owned received batch gets exactly one QualityDecision.
- No expired batch is approved.
- TEMPERATURE_EXCURSION outcome only applies to cold chain / excursion batches.
- No inventory quantity or stock movement occurs (0 ledger entries, 0 balances, 0 inventory batches).
- Segregation of duties is maintained (receiver != inspector, receiver != approver, inspector != approver).
- Resume and idempotency work cleanly.
- QualityValidator passes with 0 findings.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.db.models import F

from apps.inventory.models import InventoryBalance, InventoryBatch, InventoryLedgerEntry
from apps.platform.demo.generation import stage2b, stage2b2
from apps.platform.demo.generation.context import GenerationContext
from apps.platform.demo.generation.orchestrator import MasterDataOrchestrator
from apps.platform.demo.generation.stages import STAGES
from apps.platform.demo.generation.validation import QualityValidator, validate_demo_scenario
from apps.platform.demo.models import DemoScenarioRun
from apps.platform.demo.profiles import PILOT, get_master_data_targets
from apps.procurement.models import GoodsReceipt, QualityDecision, ReceivedBatch, ReceivingInspection
from apps.tenancy.models import Tenant

SEED = 83492011
AS_OF = date(2026, 8, 3)
PASSWORD = "Demo-Local-Pass-9182!"


def _context(tenant, run):
    return GenerationContext(
        run=run, tenant=tenant, seed=SEED, as_of=AS_OF,
        targets=get_master_data_targets("large"), demo_password=PASSWORD,
    )


@pytest.fixture
def quality_decided(db):
    """A tenant with Master Data, Procurement-Receiving (2B.1), and Quality Decisions (2B.2A)."""
    call_command_catalogue()
    tenant = Tenant.objects.create(name="S2B Quality Chemists", slug="s2bqualitytest", is_demo=True)
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
        ctx, stages=stage2b.STAGE_2B_1 + stage2b2.STAGE_2B_2A
    )
    orchestrator.run()
    return tenant, run, ctx, orchestrator


def call_command_catalogue():
    from django.core.management import call_command
    call_command("seed_medicine_catalogue", stdout=io.StringIO())


# ---------------------------------------------------------------------------
# Boundary & No-Movement Tests
# ---------------------------------------------------------------------------


def test_zero_quantity_or_stock_movement(quality_decided):
    """Recording quality decisions must move zero quantity and create zero stock."""
    tenant, *_ = quality_decided
    assert InventoryLedgerEntry.all_objects.filter(tenant=tenant).count() == 0
    assert InventoryBalance.all_objects.filter(tenant=tenant).count() == 0
    assert InventoryBatch.all_objects.filter(tenant=tenant).count() == 0

    batches = ReceivedBatch.all_objects.filter(tenant=tenant)
    assert batches.exists()
    assert not batches.filter(quality_status=ReceivedBatch.QualityStatus.RELEASED).exists()
    assert batches.filter(accepted_quantity__gt=0).count() == 0
    assert batches.exclude(quarantined_quantity=F("received_quantity")).count() == 0


def test_every_received_batch_has_exactly_one_decision(quality_decided):
    """Every received batch must have a QualityDecision record."""
    tenant, *_ = quality_decided
    batches = ReceivedBatch.all_objects.filter(tenant=tenant)
    decisions = QualityDecision.all_objects.filter(tenant=tenant)

    assert batches.count() > 0
    assert decisions.count() == batches.count()

    decided_batch_ids = set(decisions.values_list("batch_id", flat=True))
    all_batch_ids = set(batches.values_list("id", flat=True))
    assert decided_batch_ids == all_batch_ids


def test_quality_inspections_recorded(quality_decided):
    """Every GoodsReceipt must have a ReceivingInspection with QUARANTINE."""
    tenant, *_ = quality_decided
    receipts = GoodsReceipt.all_objects.filter(tenant=tenant)
    inspections = ReceivingInspection.all_objects.filter(tenant=tenant)

    assert receipts.count() > 0
    assert inspections.count() == receipts.count()
    assert not inspections.exclude(decision=ReceivingInspection.Decision.QUARANTINE).exists()


# ---------------------------------------------------------------------------
# Governance & Constraints
# ---------------------------------------------------------------------------


def test_no_expired_batch_approved(quality_decided):
    """An expired batch cannot be approved for release."""
    tenant, *_ = quality_decided
    expired_approved = QualityDecision.all_objects.filter(
        tenant=tenant,
        decision=QualityDecision.Outcome.APPROVE_FOR_RELEASE,
        batch__expiry_date__lte=AS_OF,
    )
    assert not expired_approved.exists()


def test_temperature_excursions_only_on_cold_chain(quality_decided):
    """TEMPERATURE_EXCURSION decisions only apply to cold chain or excursion-logged batches."""
    tenant, *_ = quality_decided
    excursions = QualityDecision.all_objects.filter(
        tenant=tenant,
        decision=QualityDecision.Outcome.TEMPERATURE_EXCURSION,
    ).select_related("batch__sku")

    for d in excursions:
        from apps.medicines.provisioning import _is_cold_chain
        is_cold = _is_cold_chain(d.batch.sku) or bool(d.batch.temperature_excursion)
        assert is_cold, f"Batch {d.batch.manufacturer_batch_number} is not cold chain"


def test_segregation_of_duties(quality_decided):
    """Receiver cannot inspect; receiver/inspector cannot be decision maker."""
    tenant, *_ = quality_decided

    for insp in ReceivingInspection.all_objects.filter(tenant=tenant).select_related("goods_receipt"):
        if insp.inspector_id and insp.goods_receipt.received_by_id:
            assert str(insp.inspector_id) != str(insp.goods_receipt.received_by_id)

    for d in QualityDecision.all_objects.filter(tenant=tenant).select_related("goods_receipt"):
        receiver_id = str(d.goods_receipt.received_by_id) if d.goods_receipt.received_by_id else None
        inspector_id = str(d.inspector_id) if d.inspector_id else None
        approver_id = str(d.decision_by_id) if d.decision_by_id else None

        if approver_id:
            assert approver_id != receiver_id
            assert approver_id != inspector_id


def test_evidence_basis_truth_label(quality_decided):
    """All decisions carry MANUAL_INTERNAL_QUALITY_REVIEW evidence_basis."""
    tenant, *_ = quality_decided
    decisions = QualityDecision.all_objects.filter(tenant=tenant)
    for d in decisions:
        assert d.evidence_basis == "MANUAL_INTERNAL_QUALITY_REVIEW"
        assert d.evidence_reference != ""


# ---------------------------------------------------------------------------
# Validation & Idempotency
# ---------------------------------------------------------------------------


def test_quality_validator_passes(quality_decided):
    """QualityValidator runs clean with 0 findings."""
    tenant, run, *_ = quality_decided
    res = QualityValidator(run=run, tenant=tenant).run_all()
    assert res["status"] == "PASS"
    assert res["failure_count"] == 0

    # Also test helper function
    helper_res = validate_demo_scenario(run, tenant)
    assert helper_res["status"] == "PASS"


def test_stage2b2_idempotency_and_resume(quality_decided):
    """Re-running Stage 2B.2A rehydrates and reuses all decisions with zero duplicates."""
    tenant, run, ctx, _ = quality_decided
    count_before = QualityDecision.all_objects.filter(tenant=tenant).count()

    # Create fresh orchestrator and run again with resume=True
    ctx_resume = _context(tenant, run)
    for stage in STAGES:
        stage.rehydrate(ctx_resume)

    orchestrator = MasterDataOrchestrator(
        ctx_resume, stages=stage2b.STAGE_2B_1 + stage2b2.STAGE_2B_2A
    )
    orchestrator.run(resume=True)

    count_after = QualityDecision.all_objects.filter(tenant=tenant).count()
    assert count_after == count_before

    validator_res = QualityValidator(run=run, tenant=tenant).run_all()
    assert validator_res["status"] == "PASS"
