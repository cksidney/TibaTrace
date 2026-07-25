from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.identity.models import Role, User, UserRole
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry, InventoryLocation, InventoryReservation
from apps.inventory.services import InventoryLedgerService
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient
from apps.practitioners.models import Practitioner
from apps.prescription.models import (
    DispensingAllocation,
    DispensingCheck,
    DispensingEpisode,
    DispensingLine,
    DispensingReservation,
    PatientCounselling,
    PharmacistClinicalReview,
    PharmacistVerification,
    Prescription,
    PrescriptionItem,
)
from apps.prescription.pos_dispensing_services import (
    PosBatchVerificationService,
    PosCollectionService,
    PosControlledMedicineService,
    PosCounsellingService,
    PosDispensingQueueService,
    PosPartialRepeatService,
    PosPaymentOrchestrationService,
    PosShiftService,
)
from apps.prescription.services.workflow import PrescriptionWorkflowService
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup_domain(db):
    tenant = Tenant.objects.create(name="Test Pharmacy", slug="test-pharmacy")
    org = Organization.all_objects.create(tenant=tenant, name="Main Org", code="ORG-1")
    branch = Location.all_objects.create(tenant=tenant, organization=org, name="Main Branch", code="BR-1")
    wh = InventoryLocation.all_objects.create(tenant=tenant, branch=branch, name="Main Warehouse", location_code="WH-1")

    pharmacist = User.objects.create(username="test_rph", tenant=tenant)
    cashier = User.objects.create(username="test_cashier", tenant=tenant)
    witness = User.objects.create(username="test_witness", tenant=tenant)

    patient = Patient.all_objects.create(
        tenant=tenant,
        internal_reference_id="PAT-001-REF",
        patient_number="PAT-001",
        last_name="Doe",
        first_name="John",
        sex="MALE",
        date_of_birth=date(1990, 1, 1),
    )

    practitioner = Practitioner.all_objects.create(
        tenant=tenant,
        registration_number="PRAC-001",
        last_name="Smith",
        first_name="Jane",
        profession="DOCTOR",
    )

    dose_form = DoseForm.objects.create(code="TAB", name="Tablet")
    _substance = ActiveSubstance.all_objects.create(
        tenant=tenant, code="SUB-1", canonical_name="Paracetamol", display_name="Paracetamol", search_name="paracetamol"
    )
    cmp = ClinicalMedicinalProduct.all_objects.create(tenant=tenant, code="CMP-1", canonical_name="Paracetamol 500mg", dose_form=dose_form)
    mmp = ManufacturedMedicinalProduct.all_objects.create(tenant=tenant, code="MMP-1", brand_name="Panadol", clinical_product=cmp)
    pkg = PackageDefinition.objects.create(code="PACK-1", description="Box of 100", unit_of_measure="TABLET", is_dispensing_unit=True)
    sku = CommercialSKU.all_objects.create(tenant=tenant, sku_code="SKU-PARA-500", display_name="Panadol 500mg Tab 100s", manufactured_product=mmp, package_definition=pkg)

    batch = InventoryBatch.all_objects.create(
        tenant=tenant,
        sku=sku,
        manufactured_product=mmp,
        manufacturer_batch_number="B12345",
        expiry_date=date(2028, 12, 31),
        quality_status="RELEASED",
    )

    InventoryLedgerService.post_entry(
        tenant=tenant,
        branch=branch,
        location=wh,
        sku=sku,
        inventory_batch=batch,
        entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
        quantity_delta=Decimal("100"),
        unit="TABLET",
        base_quantity_delta=Decimal("100"),
        effective_timestamp=timezone.now(),
        source_document_type="InitialStock",
        source_document_id="INIT-1",
        idempotency_key="INIT-LEDGER-1",
        actor=pharmacist,
    )

    rx = Prescription.all_objects.create(
        tenant=tenant,
        patient=patient,
        practitioner=practitioner,
        organization=org,
        location=branch,
        prescription_number="RX-1001",
        status="READY_FOR_DISPENSING",
        repeat_authorization=True,
        repeats_allowed=3,
        repeats_remaining=3,
    )

    rx_item = PrescriptionItem.all_objects.create(
        tenant=tenant,
        prescription=rx,
        prescribed_sku=sku,
        medication_name=sku.display_name,
        dosage_instruction="Take 1 tablet every 8 hours",
        quantity=Decimal("30"),
    )

    episode = DispensingEpisode.all_objects.create(
        tenant=tenant,
        dispensing_number="DISP-1001",
        prescription=rx,
        patient=patient,
        branch=branch,
        pharmacy_location=wh,
        pharmacist=pharmacist,
        status="PREPARING",
        idempotency_key="IDEMP-1001",
    )

    inv_res = InventoryReservation.all_objects.create(
        tenant=tenant,
        branch=branch,
        source_location=wh,
        sku=sku,
        requested_quantity=Decimal("30"),
        unit="TABLET",
        purpose="DISPENSING",
        idempotency_key="INV-RES-1001",
    )

    res = DispensingReservation.all_objects.create(
        tenant=tenant,
        episode=episode,
        prescription_item=rx_item,
        inventory_reservation=inv_res,
        quantity=Decimal("30"),
        idempotency_key="RES-1001",
    )

    alloc = DispensingAllocation.all_objects.create(
        tenant=tenant,
        episode=episode,
        prescription_item=rx_item,
        reservation=res,
        inventory_batch=batch,
        location=wh,
        quantity=Decimal("30"),
    )

    line = DispensingLine.all_objects.create(
        tenant=tenant,
        episode=episode,
        prescription_item=rx_item,
        prescribed_sku=sku,
        supplied_sku=sku,
        inventory_batch=batch,
        inventory_allocation=alloc,
        quantity_authorized=Decimal("30"),
        quantity_prepared=Decimal("30"),
        quantity_supplied=Decimal("0"),
        unit="TABLET",
        package_definition=pkg,
        batch_number_snapshot="B12345",
        expiry_date_snapshot=date(2028, 12, 31),
        dosage_label_instructions="Take 1 tablet every 8 hours",
        status="PREPARED",
        prepared_by=pharmacist,
    )

    return {
        "tenant": tenant,
        "branch": branch,
        "wh": wh,
        "pharmacist": pharmacist,
        "cashier": cashier,
        "witness": witness,
        "patient": patient,
        "practitioner": practitioner,
        "sku": sku,
        "batch": batch,
        "rx": rx,
        "episode": episode,
        "line": line,
    }


PHARMACIST_CAPS = [
    "dispensing.prepare",
    "dispensing.check",
    "dispensing.supply",
    "dispensing.counsel",
    "dispensing.complete",
    "prescriptions.pharmacist_verify",
    "prescriptions.controlled_verify",
    "prescriptions.approve",
    "prescriptions.record_payment",
    "pos.shift.manage",
]
CASHIER_CAPS = ["dispensing.read", "prescriptions.record_payment", "pos.shift.manage"]


def grant(user, tenant, capabilities, code="TEST_ROLE"):
    """Attach a role carrying `capabilities` to `user`."""
    role, _ = Role.all_objects.get_or_create(
        tenant=tenant,
        code=f"{code}-{user.username}",
        defaults={"name": code, "capabilities": capabilities},
    )
    role.capabilities = capabilities
    role.save()
    UserRole.all_objects.get_or_create(tenant=tenant, user=user, role=role)
    return user


@pytest.fixture
def domain(setup_domain):
    """setup_domain plus the roles the gated POS services require."""
    data = setup_domain
    grant(data["pharmacist"], data["tenant"], PHARMACIST_CAPS, "RPH")
    grant(data["cashier"], data["tenant"], CASHIER_CAPS, "CASHIER")
    grant(data["witness"], data["tenant"], PHARMACIST_CAPS, "WITNESS")
    return data


def make_clinically_ready(data):
    """Satisfy the real clinical preconditions the supply path enforces.

    Builds the verification directly rather than running the whole intake
    pipeline: what the POS gates require is a non-revoked verification whose
    context_hash still matches the prescription.
    """
    rx = data["rx"]
    actor = data["pharmacist"]
    context_hash = PrescriptionWorkflowService.context_hash(rx)

    review = PharmacistClinicalReview.all_objects.create(
        tenant=data["tenant"],
        prescription=rx,
        reviewing_pharmacist=actor,
        outcome="APPROVED",
        context_hash=context_hash,
    )
    PharmacistVerification.all_objects.create(
        tenant=data["tenant"],
        prescription=rx,
        review=review,
        verified_by=actor,
        decision="VERIFIED",
        context_hash=context_hash,
        verification_checks={"identity": True, "dose": True},
        idempotency_key=f"verify:{rx.prescription_number}",
    )
    DispensingCheck.all_objects.create(
        tenant=data["tenant"],
        episode=data["episode"],
        checked_by=actor,
        outcome="PASSED",
        checklist={"product": True, "batch": True, "quantity": True, "label": True},
    )
    PatientCounselling.all_objects.create(
        tenant=data["tenant"],
        episode=data["episode"],
        patient=data["patient"],
        counselling_required=True,
        counselling_completed=True,
    )

    # setup_domain builds the InventoryReservation row directly, so no
    # RESERVATION ledger entry backs it. The supply path releases against those
    # entries, so post the reservation the way reserve_stock would.
    line = data["line"]
    reservation = line.inventory_allocation.reservation.inventory_reservation
    InventoryLedgerService.post_entry(
        tenant=data["tenant"],
        branch=data["branch"],
        location=data["wh"],
        sku=line.supplied_sku,
        inventory_batch=line.inventory_batch,
        entry_type=InventoryLedgerEntry.EntryType.RESERVATION,
        quantity_delta=line.quantity_authorized,
        unit=line.unit,
        base_quantity_delta=line.quantity_authorized,
        effective_timestamp=timezone.now(),
        source_document_type="RESERVATION",
        source_document_id=str(reservation.pk),
        idempotency_key=f"reserve:{reservation.pk}",
        actor=actor,
    )


def advance_to_ready_for_supply(data):
    """Walk the episode through the real gated transitions to READY_FOR_SUPPLY."""
    episode = data["episode"]
    rph = data["pharmacist"]
    PosDispensingQueueService.transition_state(episode=episode, new_status="CHECKING", actor=rph)
    episode.refresh_from_db()
    PosDispensingQueueService.transition_state(
        episode=episode, new_status="READY_FOR_SUPPLY", actor=rph
    )
    episode.refresh_from_db()
    return episode


def test_queue_service_fetches_episodes(setup_domain):
    data = setup_domain
    queue = PosDispensingQueueService.get_queue(tenant=data["tenant"], branch=data["branch"])
    assert queue.count() == 1
    assert queue.first().dispensing_number == "DISP-1001"


def test_transition_state_validates_lifecycle(domain):
    data = domain
    episode = data["episode"]
    rph = data["pharmacist"]

    ep = PosDispensingQueueService.transition_state(
        episode=episode, new_status="CHECKING", actor=rph
    )
    assert ep.status == "CHECKING"

    # CHECKING -> READY_FOR_PAYMENT is gated on verification + final check.
    with pytest.raises(ValidationError):
        PosDispensingQueueService.transition_state(
            episode=ep, new_status="READY_FOR_PAYMENT", actor=rph
        )

    make_clinically_ready(data)
    ep.refresh_from_db()
    ep = PosDispensingQueueService.transition_state(
        episode=ep, new_status="READY_FOR_PAYMENT", actor=rph
    )
    assert ep.status == "READY_FOR_PAYMENT"


def test_transition_state_rejects_illegal_transition(domain):
    data = domain
    with pytest.raises(ValidationError, match="Invalid state transition"):
        PosDispensingQueueService.transition_state(
            episode=data["episode"], new_status="SUPPLIED", actor=data["pharmacist"]
        )


def test_batch_verification_success_and_failure(setup_domain):
    data = setup_domain
    sku = data["sku"]

    res = PosBatchVerificationService.verify_batch(
        tenant=data["tenant"], sku_id=sku.id, batch_number="B12345", quantity_scanned=Decimal("1")
    )
    assert res["valid"]
    assert res["release_status"] == "RELEASED"

    res_bad = PosBatchVerificationService.verify_batch(
        tenant=data["tenant"], sku_id=sku.id, batch_number="INVALID_BATCH"
    )
    assert not res_bad["valid"]
    assert "not found" in res_bad["reason"]


def test_batch_verification_rejects_mismatched_expiry(setup_domain):
    data = setup_domain
    res = PosBatchVerificationService.verify_batch(
        tenant=data["tenant"],
        sku_id=data["sku"].id,
        batch_number="B12345",
        expiry_date=date(2027, 1, 1),
    )
    assert not res["valid"]
    assert "does not match batch record" in res["reason"]


def test_payment_orchestration_links_payment_without_inventory_deduction(domain):
    data = domain
    make_clinically_ready(data)
    episode = data["episode"]
    rph = data["pharmacist"]

    PosDispensingQueueService.transition_state(episode=episode, new_status="CHECKING", actor=rph)
    episode.refresh_from_db()
    PosDispensingQueueService.transition_state(
        episode=episode, new_status="READY_FOR_PAYMENT", actor=rph
    )
    episode.refresh_from_db()

    res = PosPaymentOrchestrationService.process_payment(
        episode=episode,
        tender_type="MPESA",
        paid_amount=Decimal("150.00"),
        payment_reference="MPESA-REF-999",
        cashier=data["cashier"],
        idempotency_key="PAY-KEY-1",
    )

    assert res["success"]
    assert res["payment_state"] == "PAID"
    episode.refresh_from_db()
    assert episode.status == "PAID"
    assert episode.paid_amount == Decimal("150.00")
    # One canonical field now carries settlement.
    assert episode.payment_state == "PAID"

    # Payment must not deduct stock: only the RECEIPT and RESERVATION exist.
    assert not InventoryLedgerEntry.all_objects.filter(
        tenant=data["tenant"], entry_type=InventoryLedgerEntry.EntryType.ISSUE
    ).exists()


def test_partial_dispensing_posts_inventory_and_leaves_balance(domain):
    data = domain
    make_clinically_ready(data)
    episode = advance_to_ready_for_supply(data)

    res = PosPartialRepeatService.dispense_partial(
        episode=episode,
        dispensing_line_id=data["line"].id,
        quantity_supplied=Decimal("10"),
        reason="Patient requested partial supply",
        actor=data["pharmacist"],
        idempotency_key="PARTIAL-1",
    )

    assert res["outstanding_balance"] == "20.0000"
    assert res["status"] == "PARTIALLY_SUPPLIED"

    # Unlike before, a partial supply now moves stock for the supplied quantity.
    issued = InventoryLedgerEntry.all_objects.filter(
        tenant=data["tenant"], entry_type=InventoryLedgerEntry.EntryType.ISSUE
    )
    assert issued.count() == 1
    assert sum(e.quantity_delta for e in issued) == Decimal("-10.0000")


def test_repeat_eligibility_is_advisory_only(setup_domain):
    data = setup_domain
    info = PosPartialRepeatService.check_repeat_eligibility(
        tenant=data["tenant"], prescription_id=data["rx"].id
    )
    assert info["eligible"]
    assert info["repeats_remaining"] == 3
    # The probe must never be mistaken for a claim on a repeat.
    assert info["advisory_only"] is True


def test_controlled_medicine_verification(domain):
    data = domain
    episode = data["episode"]
    practitioner = data["practitioner"]
    practitioner.controlled_medicine_authority = True
    practitioner.save()

    res = PosControlledMedicineService.verify_controlled_authority(
        episode=episode,
        practitioner_id=practitioner.id,
        collector_id_number="ID-998877",
        witness=data["witness"],
        actor=data["pharmacist"],
    )

    assert res["verified"]
    episode.refresh_from_db()
    assert episode.controlled_authority_checked
    assert episode.collector_id_number == "ID-998877"
    assert episode.controlled_witness == data["witness"]


def test_controlled_verification_rejects_unauthorised_prescriber(domain):
    data = domain
    practitioner = data["practitioner"]
    practitioner.controlled_medicine_authority = False
    practitioner.save()

    with pytest.raises(ValidationError, match="not authorised"):
        PosControlledMedicineService.verify_controlled_authority(
            episode=data["episode"],
            practitioner_id=practitioner.id,
            collector_id_number="ID-998877",
            witness=data["witness"],
            actor=data["pharmacist"],
        )


def test_controlled_verification_requires_distinct_witness(domain):
    data = domain
    practitioner = data["practitioner"]
    practitioner.controlled_medicine_authority = True
    practitioner.save()

    with pytest.raises(ValidationError, match="must differ"):
        PosControlledMedicineService.verify_controlled_authority(
            episode=data["episode"],
            practitioner_id=practitioner.id,
            collector_id_number="ID-998877",
            witness=data["pharmacist"],
            actor=data["pharmacist"],
        )


def test_counselling_recording(domain):
    data = domain
    episode = data["episode"]

    counselling = PosCounsellingService.record_counselling(
        episode=episode,
        pharmacist=data["pharmacist"],
        notes="Discussed taking with food.",
    )

    assert counselling.counselling_completed
    assert counselling.counselled_by == data["pharmacist"]
    episode.refresh_from_db()
    assert episode.counselling_status == "COMPLETED"


def test_collection_confirms_supply_and_posts_inventory(domain):
    data = domain
    make_clinically_ready(data)
    episode = advance_to_ready_for_supply(data)

    supply = PosCollectionService.confirm_collection(
        episode=episode,
        collector_name="John Doe",
        collector_id_number="ID-12345",
        collector_phone="0712345678",
        collector_relationship="SELF",
        collection_proof_type="SIGNATURE",
        signature_ref="SIG-REF-001",
        actor=data["pharmacist"],
        idempotency_key="COLLECT-KEY-1",
    )

    assert supply.status == "COMPLETE"
    episode.refresh_from_db()
    assert episode.status == "SUPPLIED"
    assert episode.collector_name == "John Doe"

    issued = InventoryLedgerEntry.all_objects.filter(
        tenant=data["tenant"], entry_type=InventoryLedgerEntry.EntryType.ISSUE
    )
    assert issued.count() == 1
    assert issued.first().quantity_delta == Decimal("-30.0000")


def test_shift_operations_reconciliation(domain):
    data = domain
    tenant = data["tenant"]
    rph = data["pharmacist"]

    shift = PosShiftService.start_shift(
        tenant=tenant,
        shift_number="SHIFT-001",
        cashier=data["cashier"],
        pharmacist=rph,
        location=data["branch"],
        controlled_start_count=50,
        actor=rph,
    )
    assert shift.status == "OPEN"

    ended = PosShiftService.end_shift(
        shift=shift, controlled_end_count=50, declaration_notes="All clear", actor=rph
    )
    assert ended.status == "CLOSED"
    # The seeded episode is still PREPARING, so nothing is outstanding.
    assert ended.outstanding_episode_count == 0
    assert not ended.discrepancy_declared

    shift2 = PosShiftService.start_shift(
        tenant=tenant,
        shift_number="SHIFT-002",
        cashier=data["cashier"],
        pharmacist=rph,
        location=data["branch"],
        controlled_start_count=50,
        actor=rph,
    )
    ended2 = PosShiftService.end_shift(
        shift=shift2, controlled_end_count=48, declaration_notes="Discrepancy found", actor=rph
    )
    assert ended2.discrepancy_declared


def test_shift_close_flags_outstanding_episodes(domain):
    data = domain
    make_clinically_ready(data)
    advance_to_ready_for_supply(data)
    rph = data["pharmacist"]

    shift = PosShiftService.start_shift(
        tenant=data["tenant"],
        shift_number="SHIFT-003",
        cashier=data["cashier"],
        pharmacist=rph,
        location=data["branch"],
        controlled_start_count=10,
        actor=rph,
    )
    ended = PosShiftService.end_shift(shift=shift, controlled_end_count=10, actor=rph)

    # An episode awaiting supply must be visible at shift close.
    assert ended.outstanding_episode_count == 1
    assert ended.discrepancy_declared


def test_shift_cannot_be_closed_twice(domain):
    data = domain
    rph = data["pharmacist"]
    shift = PosShiftService.start_shift(
        tenant=data["tenant"],
        shift_number="SHIFT-004",
        cashier=data["cashier"],
        pharmacist=rph,
        location=data["branch"],
        actor=rph,
    )
    PosShiftService.end_shift(shift=shift, controlled_end_count=0, actor=rph)
    shift.refresh_from_db()
    with pytest.raises(ValidationError, match="not open"):
        PosShiftService.end_shift(shift=shift, controlled_end_count=0, actor=rph)
