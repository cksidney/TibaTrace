"""Stage 2B.1 — procurement and receiving.

The load-bearing tests are the boundary ones. A generator that produced a
plausible procurement history while quietly releasing quality, posting a
receipt or writing a ledger entry would create available-to-promise stock that
no quality decision ever authorised, and its own summary would look correct.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db.models import F

from apps.inventory.models import InventoryBalance, InventoryBatch, InventoryLedgerEntry
from apps.platform.demo.generation import stage2b
from apps.platform.demo.generation.context import GenerationContext
from apps.platform.demo.generation.orchestrator import MasterDataOrchestrator
from apps.platform.demo.generation.stages import STAGES
from apps.platform.demo.models import DemoScenarioObject, DemoScenarioRun
from apps.platform.demo.profiles import PILOT, get_master_data_targets
from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderRevision,
    PurchaseRequisition,
    ReceivedBatch,
)
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
def procured(db):
    """A tenant with Stage 2A master data and Stage 2B.1 procurement run."""
    call_command("seed_medicine_catalogue", stdout=io.StringIO())
    tenant = Tenant.objects.create(name="S2B Chemists", slug="s2btest", is_demo=True)
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
    orchestrator = MasterDataOrchestrator(ctx, stages=stage2b.STAGE_2B_1)
    orchestrator.run()
    return tenant, run, ctx, orchestrator


def _rehydrated(tenant, run):
    ctx = _context(tenant, run)
    for stage in STAGES:
        stage.rehydrate(ctx)
    return ctx


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------


def test_no_inventory_is_created(procured):
    """The whole point of the increment: received is not available."""
    tenant, *_ = procured
    assert InventoryLedgerEntry.all_objects.filter(tenant=tenant).count() == 0
    assert InventoryBalance.all_objects.filter(tenant=tenant).count() == 0
    assert InventoryBatch.all_objects.filter(tenant=tenant).count() == 0


def test_every_received_batch_is_fully_held(procured):
    """Held, not released -- and held on quantity, not just on a status label.

    capture_batch leaves quality_status at PENDING_INSPECTION and quarantines
    the whole delivery. Asserting on the status alone would pass a batch whose
    units had been released.
    """
    tenant, *_ = procured
    batches = ReceivedBatch.all_objects.filter(tenant=tenant)
    assert batches.exists()
    assert not batches.filter(
        quality_status=ReceivedBatch.QualityStatus.RELEASED
    ).exists()
    assert batches.exclude(quarantined_quantity=F("received_quantity")).count() == 0
    assert batches.filter(accepted_quantity__gt=0).count() == 0


def test_closure_refuses_if_anything_was_released(procured):
    """N4 asserts the boundary rather than trusting it."""
    tenant, run, ctx, _o = procured
    batch = ReceivedBatch.all_objects.filter(tenant=tenant).order_by("pk").first()
    batch.quality_status = ReceivedBatch.QualityStatus.RELEASED
    batch.save(update_fields=["quality_status"])

    with pytest.raises(ValidationError, match="RELEASED"):
        stage2b.StageN4ReceiptClosure().run(_rehydrated(tenant, run))


# ---------------------------------------------------------------------------
# Volumes and shape
# ---------------------------------------------------------------------------


def test_generated_volumes_sit_inside_the_authorised_bands(procured):
    tenant, _run, ctx, _o = procured
    assert 8 <= PurchaseRequisition.all_objects.filter(tenant=tenant).count() <= 12
    assert 12 <= PurchaseOrder.all_objects.filter(tenant=tenant).count() <= 20
    assert 10 <= GoodsReceipt.all_objects.filter(tenant=tenant).count() <= 16
    assert 80 <= GoodsReceiptLine.all_objects.filter(tenant=tenant).count() <= 140
    assert 100 <= ReceivedBatch.all_objects.filter(tenant=tenant).count() <= 180


def test_every_order_derives_from_an_approved_requisition(procured):
    tenant, *_ = procured
    for order in PurchaseOrder.all_objects.filter(tenant=tenant):
        assert order.originating_requisition_id is not None


def test_orders_reach_a_received_state(procured):
    tenant, *_ = procured
    statuses = set(
        PurchaseOrder.all_objects.filter(tenant=tenant).values_list("status", flat=True)
    )
    assert statuses <= {
        PurchaseOrder.Status.FULLY_RECEIVED,
        PurchaseOrder.Status.PARTIALLY_RECEIVED,
    }


def test_revisions_are_recorded_and_reapproved(procured):
    """A revision resets approval; the order must not ship on the old one."""
    tenant, *_ = procured
    revisions = PurchaseOrderRevision.all_objects.filter(tenant=tenant)
    assert revisions.exists()
    for revision in revisions:
        assert revision.change_reason
        assert revision.previous_snapshot
        # The order moved on past SUBMITTED, so it was approved again.
        assert revision.purchase_order.status != PurchaseOrder.Status.SUBMITTED


def test_delivery_notes_are_unique_per_supplier(procured):
    tenant, *_ = procured
    seen = set()
    for receipt in GoodsReceipt.all_objects.filter(tenant=tenant).select_related("supplier"):
        key = (receipt.supplier_id, receipt.delivery_note_number)
        assert key not in seen, "a delivery note was reused for one supplier"
        seen.add(key)


def test_batch_dates_are_coherent(procured):
    tenant, *_ = procured
    for batch in ReceivedBatch.all_objects.filter(tenant=tenant):
        assert batch.expiry_date > AS_OF - timedelta(days=400)
        if batch.manufacture_date:
            assert batch.manufacture_date < batch.expiry_date
        assert batch.received_quantity > 0


def test_received_quantity_never_exceeds_ordered(procured):
    tenant, *_ = procured
    for line in GoodsReceiptLine.all_objects.filter(tenant=tenant).select_related("po_line"):
        assert line.delivered_quantity <= line.po_line.ordered_quantity


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


def test_supplier_qualification_gates_the_order(db):
    """A supplier without the licence cannot be sent a controlled line."""
    from apps.procurement.models import Supplier
    from apps.procurement.services.supplier_governance_service import (
        SupplierGovernanceService,
    )
    from apps.procurement.services.supplier_qualification_service import (
        SupplierQualificationService,
    )

    tenant = Tenant.objects.create(name="Gate", slug="gatetest", is_demo=True)
    supplier = SupplierGovernanceService.create_supplier(
        tenant=tenant, supplier_code="GATE-1", legal_name="Gate Distributors"
    )
    from apps.identity.models import User

    actor = User.objects.create(username="gate.actor", tenant=tenant, is_superuser=True)
    SupplierGovernanceService.approve_supplier(
        supplier=supplier, approver=actor, reason="approved"
    )
    supplier.refresh_from_db()
    assert supplier.status == Supplier.Status.APPROVED

    # No qualifications yet: baseline requirements are unmet.
    reasons = SupplierGovernanceService.ineligibility_reasons(supplier=supplier)
    assert reasons, "an unqualified supplier must not be orderable"
    assert not SupplierQualificationService.holds(
        supplier=supplier, qualification_type="CONTROLLED_DRUG_LICENCE"
    )


def test_the_order_raiser_cannot_approve_it(procured):
    """Recorded creator plus the SoD check added in this increment."""
    tenant, _run, ctx, _o = procured
    from apps.procurement.services.procurement_service import ProcurementService

    order = PurchaseOrder.all_objects.filter(tenant=tenant).order_by("po_number").first()
    assert order.created_by_id is not None, "the raiser must be recorded"
    order.status = PurchaseOrder.Status.DRAFT
    order.save(update_fields=["status"])

    with pytest.raises(ValidationError, match="cannot approve"):
        ProcurementService.approve_purchase_order(
            purchase_order=order, approver=order.created_by
        )


def test_the_requester_cannot_approve_their_own_requisition(procured):
    tenant, *_ = procured
    from apps.procurement.services.procurement_service import ProcurementService

    requisition = PurchaseRequisition.all_objects.filter(tenant=tenant).first()
    with pytest.raises(ValidationError, match="Requester cannot approve"):
        ProcurementService.approve_requisition(
            requisition=requisition, approver=requisition.requester
        )


# ---------------------------------------------------------------------------
# Ownership, determinism, idempotency, resume
# ---------------------------------------------------------------------------


def test_every_generated_object_is_demo_owned(procured):
    _t, run, *_ = procured
    owned = DemoScenarioObject.all_objects.filter(
        run=run, stage__in=[s.id for s in stage2b.STAGE_2B_1]
    )
    assert owned.count() > 0
    assert owned.filter(external_reference="").count() == 0
    assert set(owned.values_list("story_id", flat=True)) <= {
        stage2b.STORY_PROCUREMENT, stage2b.STORY_RECEIVING,
    }


def test_batches_are_recorded_as_non_resettable(procured):
    """A received batch is receipt evidence; archival supersedes it."""
    _t, run, *_ = procured
    batches = DemoScenarioObject.all_objects.filter(run=run, domain="received_batches")
    assert batches.exists()
    assert batches.filter(reset_eligible=True).count() == 0


def test_an_identical_rerun_creates_no_duplicates(procured):
    tenant, run, _ctx, _o = procured
    before = {
        "requisitions": PurchaseRequisition.all_objects.filter(tenant=tenant).count(),
        "orders": PurchaseOrder.all_objects.filter(tenant=tenant).count(),
        "revisions": PurchaseOrderRevision.all_objects.filter(tenant=tenant).count(),
        "receipts": GoodsReceipt.all_objects.filter(tenant=tenant).count(),
        "lines": GoodsReceiptLine.all_objects.filter(tenant=tenant).count(),
        "batches": ReceivedBatch.all_objects.filter(tenant=tenant).count(),
    }
    run.refresh_from_db()
    MasterDataOrchestrator(
        _rehydrated(tenant, run), stages=stage2b.STAGE_2B_1
    ).run()
    after = {
        "requisitions": PurchaseRequisition.all_objects.filter(tenant=tenant).count(),
        "orders": PurchaseOrder.all_objects.filter(tenant=tenant).count(),
        "revisions": PurchaseOrderRevision.all_objects.filter(tenant=tenant).count(),
        "receipts": GoodsReceipt.all_objects.filter(tenant=tenant).count(),
        "lines": GoodsReceiptLine.all_objects.filter(tenant=tenant).count(),
        "batches": ReceivedBatch.all_objects.filter(tenant=tenant).count(),
    }
    assert before == after


def test_resume_does_not_repeat_completed_transitions(procured, monkeypatch):
    """Approvals, revisions and sends must not be replayed."""
    tenant, run, _ctx, _o = procured
    run.refresh_from_db()
    progress = dict(run.stage_progress)
    for stage_id in ("N3", "N4"):
        progress.pop(stage_id, None)
    run.stage_progress = progress
    run.save(update_fields=["stage_progress"])

    revisions_before = PurchaseOrderRevision.all_objects.filter(tenant=tenant).count()
    batches_before = ReceivedBatch.all_objects.filter(tenant=tenant).count()

    messages = []
    MasterDataOrchestrator(
        _rehydrated(tenant, run), progress=messages.append, stages=stage2b.STAGE_2B_1
    ).run(resume=True)

    assert len([m for m in messages if "rehydrated" in m]) == 6
    assert PurchaseOrderRevision.all_objects.filter(tenant=tenant).count() == (
        revisions_before
    )
    assert ReceivedBatch.all_objects.filter(tenant=tenant).count() == batches_before


def test_a_failed_stage_records_where_to_resume_from(db, monkeypatch):
    call_command("seed_medicine_catalogue", stdout=io.StringIO())
    tenant = Tenant.objects.create(name="Fail", slug="s2bfail", is_demo=True)
    run = DemoScenarioRun.all_objects.create(
        tenant=tenant, scenario_name="nairobi-chemists", scenario_version="1.0.0",
        profile=PILOT.key, random_seed=SEED, as_of_date=AS_OF, scale="large",
        demo_version="2026.08.03",
    )
    MasterDataOrchestrator(_context(tenant, run)).run()
    run.refresh_from_db()

    def exploding(self, ctx):
        raise RuntimeError("simulated interruption during batch capture")

    monkeypatch.setattr(stage2b.StageN3BatchCapture, "run", exploding)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        MasterDataOrchestrator(
            _rehydrated(tenant, run), stages=stage2b.STAGE_2B_1
        ).run()

    run.refresh_from_db()
    completed = {k for k, v in run.stage_progress.items() if v["status"] == "COMPLETED"}
    assert {"M1", "M2", "M3", "M4", "M5", "N1"} <= completed
    assert run.stage_progress["N3"]["status"] == "FAILED"
    assert run.stage_progress["N3"]["error_class"] == "RuntimeError"


def test_generation_is_deterministic_across_tenants(db):
    """Same seed, same plan: batch numbers and quantities must match."""
    call_command("seed_medicine_catalogue", stdout=io.StringIO())
    shapes = []
    for slug in ("det2b-a", "det2b-b"):
        tenant = Tenant.objects.create(name="Det", slug=slug, is_demo=True)
        run = DemoScenarioRun.all_objects.create(
            tenant=tenant, scenario_name="nairobi-chemists", scenario_version="1.0.0",
            profile=PILOT.key, random_seed=SEED, as_of_date=AS_OF, scale="large",
            demo_version="2026.08.03",
        )
        MasterDataOrchestrator(_context(tenant, run)).run()
        run.refresh_from_db()
        MasterDataOrchestrator(
            _rehydrated(tenant, run), stages=stage2b.STAGE_2B_1
        ).run()
        shapes.append(
            list(
                ReceivedBatch.all_objects.filter(tenant=tenant)
                .order_by("manufacturer_batch_number")
                .values_list(
                    "manufacturer_batch_number", "received_quantity", "expiry_date"
                )
            )
        )
    assert shapes[0] == shapes[1]
    assert shapes[0], "no batches were generated"
