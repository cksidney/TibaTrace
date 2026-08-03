"""Per-batch quality decisions.

The service exists because reviewing a batch and releasing it were the same
event. `release_quarantined_batch` was the only way to record a
`QualityDecision`, and it set `quality_status` to RELEASED -- so there was no
state in which stock had been assessed but not yet handed to the shelf.

These tests are mostly about what recording a decision does *not* do.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.identity.models import User
from apps.inventory.models import InventoryBalance, InventoryBatch, InventoryLedgerEntry
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    Manufacturer,
    PackageDefinition,
)
from apps.organizations.services import (
    OrganizationProvisioningService,
    SiteProvisioningService,
)
from apps.procurement.models import QualityDecision, ReceivedBatch
from apps.procurement.services.batch_quality_service import (
    MANUAL_QUALITY_REVIEW,
    BatchQualityDecisionService,
)
from apps.procurement.services.procurement_service import ProcurementService
from apps.procurement.services.receiving_service import GoodsReceivingService
from apps.procurement.services.supplier_governance_service import (
    SupplierGovernanceService,
)
from apps.tenancy.models import Tenant

Outcome = QualityDecision.Outcome
TODAY = date(2026, 8, 3)


@pytest.fixture
def world(db):
    """A received, quarantined batch with three distinct actors."""
    tenant = Tenant.objects.create(name="Quality Chemists", slug="qualitychem")
    receiver = User.objects.create(username="q.receiver", tenant=tenant, is_superuser=True)
    inspector = User.objects.create(username="q.inspector", tenant=tenant, is_superuser=True)
    approver = User.objects.create(username="q.approver", tenant=tenant, is_superuser=True)

    org = OrganizationProvisioningService.provision_organization(
        tenant=tenant, code="Q-ORG", name="Quality Ltd"
    )
    branch = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="Q-WH", name="Warehouse",
        site_type="WAREHOUSE",
    )
    form = DoseForm.objects.create(code="TAB", name="Tablet")
    manufacturer = Manufacturer.objects.create(
        code="Q-MFR", is_global=True, legal_name="Global Pharma", country="IN"
    )
    clinical = ClinicalMedicinalProduct.objects.create(
        is_global=True, code="Q-CMP", canonical_name="Paracetamol 500mg",
        dose_form=form, status=ClinicalMedicinalProduct.STATUS_ACTIVE,
    )
    product = ManufacturedMedicinalProduct.objects.create(
        is_global=True, code="Q-MP", brand_name="Panadol", clinical_product=clinical,
        manufacturer=manufacturer, status=ManufacturedMedicinalProduct.STATUS_ACTIVE,
    )
    package = PackageDefinition.objects.create(
        code="Q-PKG", description="Box of 30", unit_of_measure="tablet", is_active=True
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="Q-SKU-001", display_name="Panadol 30s",
        manufactured_product=product, package_definition=package,
        status=CommercialSKU.STATUS_ACTIVE,
    )
    supplier = SupplierGovernanceService.create_supplier(
        tenant=tenant, supplier_code="Q-SUP", legal_name="Quality Distributors"
    )
    SupplierGovernanceService.approve_supplier(
        supplier=supplier, approver=approver, reason="approved"
    )
    supplier.refresh_from_db()

    order = ProcurementService.create_purchase_order(
        tenant=tenant, supplier=supplier, ordering_branch=branch,
        lines_data=[{"sku": sku, "quantity": 100, "unit_cost": "10.00"}],
        created_by=receiver, po_number="Q-PO-1",
    )
    ProcurementService.approve_purchase_order(purchase_order=order, approver=approver)
    ProcurementService.send_po(purchase_order=order)

    receipt = GoodsReceivingService.start_goods_receipt(
        tenant=tenant, grn_number="Q-GRN-1", purchase_order=order,
        receiving_branch=branch, receiver=receiver, delivery_note_number="Q-DN-1",
    )
    po_line = order.lines.first() or __import__(
        "apps.procurement.models", fromlist=["PurchaseOrderLine"]
    ).PurchaseOrderLine.all_objects.filter(tenant=tenant, purchase_order=order).first()
    batch = GoodsReceivingService.receive_batch(
        goods_receipt=receipt, po_line=po_line,
        manufacturer_batch_number="Q-BATCH-001",
        expiry_date=TODAY + timedelta(days=400),
        received_quantity=100,
        manufacture_date=TODAY - timedelta(days=60),
        idempotency_key="Q-BATCH-001",
    )
    return {
        "tenant": tenant, "receiver": receiver, "inspector": inspector,
        "approver": approver, "batch": batch, "receipt": receipt, "sku": sku,
    }


def _record(world, outcome=Outcome.APPROVE_FOR_RELEASE, **kwargs):
    return BatchQualityDecisionService.record_decision(
        batch=kwargs.pop("batch", world["batch"]),
        inspector=kwargs.pop("inspector", world["inspector"]),
        decision_by=kwargs.pop("decision_by", world["approver"]),
        outcome=outcome,
        reason=kwargs.pop("reason", "Inspected on arrival; packaging intact."),
        as_of=kwargs.pop("as_of", TODAY),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# The boundary: a decision moves nothing
# ---------------------------------------------------------------------------


def test_approval_does_not_release_or_move_quantity(world):
    """The whole reason the service exists."""
    batch = world["batch"]
    before = (
        batch.quality_status, batch.received_quantity,
        batch.quarantined_quantity, batch.accepted_quantity, batch.rejected_quantity,
    )
    _record(world, Outcome.APPROVE_FOR_RELEASE)
    batch.refresh_from_db()
    after = (
        batch.quality_status, batch.received_quantity,
        batch.quarantined_quantity, batch.accepted_quantity, batch.rejected_quantity,
    )
    assert before == after
    assert batch.quality_status != ReceivedBatch.QualityStatus.RELEASED
    assert batch.quarantined_quantity == batch.received_quantity
    assert batch.accepted_quantity == 0


def test_no_decision_creates_inventory(world):
    tenant = world["tenant"]
    for outcome in (Outcome.APPROVE_FOR_RELEASE,):
        _record(world, outcome)
    assert InventoryLedgerEntry.all_objects.filter(tenant=tenant).count() == 0
    assert InventoryBalance.all_objects.filter(tenant=tenant).count() == 0
    assert InventoryBatch.all_objects.filter(tenant=tenant).count() == 0


def test_rejection_retains_the_batch(world):
    """A rejected batch is evidence; it is not deleted, and it does not move."""
    batch = world["batch"]
    _record(world, Outcome.REJECT, reason="Packaging integrity failure.")
    batch.refresh_from_db()
    assert ReceivedBatch.all_objects.filter(pk=batch.pk).exists()
    assert batch.quarantined_quantity == batch.received_quantity
    assert batch.rejected_quantity == 0, "recording a rejection must not move quantity"


def test_approval_marks_the_batch_releasable_without_releasing_it(world):
    assert BatchQualityDecisionService.is_releasable(batch=world["batch"]) is False
    _record(world, Outcome.APPROVE_FOR_RELEASE)
    assert BatchQualityDecisionService.is_releasable(batch=world["batch"]) is True
    world["batch"].refresh_from_db()
    assert world["batch"].quality_status != ReceivedBatch.QualityStatus.RELEASED


@pytest.mark.parametrize("outcome", [
    Outcome.HOLD_FOR_REVIEW, Outcome.REJECT, Outcome.DAMAGE_HOLD,
    Outcome.DOCUMENTATION_HOLD, Outcome.NEAR_EXPIRY_HOLD,
])
def test_non_approval_outcomes_are_not_releasable(world, outcome):
    _record(world, outcome, reason="Held pending review.")
    assert BatchQualityDecisionService.is_releasable(batch=world["batch"]) is False


# ---------------------------------------------------------------------------
# Segregation of duties
# ---------------------------------------------------------------------------


def test_the_receiver_cannot_inspect_their_own_delivery(world):
    """Receiving and quality are the two halves of the control."""
    with pytest.raises(PermissionDenied, match="cannot inspect"):
        _record(world, inspector=world["receiver"])


def test_the_receiver_cannot_sign_off_the_decision(world):
    with pytest.raises(PermissionDenied, match="cannot sign off"):
        _record(world, decision_by=world["receiver"])


def test_an_inspector_and_a_decision_maker_are_both_required(world):
    with pytest.raises(PermissionDenied, match="inspector"):
        _record(world, inspector=None)
    with pytest.raises(PermissionDenied, match="decision maker"):
        _record(world, decision_by=None)


def test_a_reason_is_required(world):
    with pytest.raises(ValidationError, match="reason"):
        _record(world, reason="   ")


# ---------------------------------------------------------------------------
# Correctness of the decision itself
# ---------------------------------------------------------------------------


def test_an_expired_batch_cannot_be_approved(world):
    """Approval is what a later release keys off."""
    batch = world["batch"]
    batch.expiry_date = TODAY - timedelta(days=1)
    batch.save(update_fields=["expiry_date"])
    with pytest.raises(ValidationError, match="expired"):
        _record(world, Outcome.APPROVE_FOR_RELEASE)
    # It can still be held or rejected -- that is the correct disposition.
    decision = _record(world, Outcome.REJECT, reason="Expired on arrival.")
    assert decision.decision == Outcome.REJECT


def test_temperature_excursion_only_applies_to_temperature_sensitive_lines(world):
    with pytest.raises(ValidationError, match="not a temperature-sensitive"):
        _record(world, Outcome.TEMPERATURE_EXCURSION, reason="Excursion logged.")

    decision = _record(
        world, Outcome.TEMPERATURE_EXCURSION,
        reason="Cold-chain excursion logged on arrival.",
        requires_cold_chain=True,
    )
    assert decision.decision == Outcome.TEMPERATURE_EXCURSION


def test_an_unknown_outcome_is_refused(world):
    with pytest.raises(ValidationError, match="Unknown quality outcome"):
        _record(world, "LOOKS_FINE_TO_ME")


def test_a_batch_already_out_of_review_cannot_be_decided(world):
    batch = world["batch"]
    batch.quality_status = ReceivedBatch.QualityStatus.RELEASED
    batch.save(update_fields=["quality_status"])
    with pytest.raises(ValidationError, match="no longer in review"):
        _record(world)


# ---------------------------------------------------------------------------
# Evidence, idempotency and collisions
# ---------------------------------------------------------------------------


def test_the_decision_records_honest_evidence(world):
    """Nothing contacted a regulator, so nothing claims to."""
    decision = _record(world, evidence_reference="Q-EVIDENCE-1")
    assert decision.evidence_basis == MANUAL_QUALITY_REVIEW
    assert decision.evidence_reference == "Q-EVIDENCE-1"
    assert decision.inspector_id == world["inspector"].pk
    assert decision.decision_by_id == world["approver"].pk
    assert decision.decision_notes


def test_recording_the_same_decision_twice_is_idempotent(world):
    first = _record(world, Outcome.APPROVE_FOR_RELEASE)
    second = _record(world, Outcome.APPROVE_FOR_RELEASE)
    assert first.pk == second.pk
    assert QualityDecision.all_objects.filter(batch=world["batch"]).count() == 1


def test_a_conflicting_decision_is_refused_rather_than_overwritten(world):
    """A recorded decision is evidence of what quality concluded."""
    _record(world, Outcome.APPROVE_FOR_RELEASE)
    with pytest.raises(ValidationError, match="already has a"):
        _record(world, Outcome.REJECT, reason="Changed my mind.")
    assert QualityDecision.all_objects.filter(batch=world["batch"]).count() == 1


def test_one_decision_per_batch_is_enforced_by_the_database(world):
    """The service checks it; the constraint means nothing else can bypass it."""
    from django.db import IntegrityError, transaction

    _record(world, Outcome.APPROVE_FOR_RELEASE)
    with pytest.raises(IntegrityError), transaction.atomic():
        QualityDecision.all_objects.create(
            tenant=world["tenant"], goods_receipt=world["receipt"],
            batch=world["batch"], decision=Outcome.REJECT,
            decision_by=world["approver"],
        )
