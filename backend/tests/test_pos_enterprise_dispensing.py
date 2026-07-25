from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.identity.models import User
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
    DispensingEpisode,
    DispensingLine,
    DispensingReservation,
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


def test_queue_service_fetches_episodes(setup_domain):
    data = setup_domain
    queue = PosDispensingQueueService.get_queue(tenant=data["tenant"], branch=data["branch"])
    assert queue.count() == 1
    assert queue.first().dispensing_number == "DISP-1001"


def test_transition_state_validates_lifecycle(setup_domain):
    data = setup_domain
    episode = data["episode"]

    # PREPARING -> CHECKING
    ep = PosDispensingQueueService.transition_state(episode=episode, new_status="CHECKING", actor=data["pharmacist"])
    assert ep.status == "CHECKING"

    # CHECKING -> READY_FOR_PAYMENT
    ep = PosDispensingQueueService.transition_state(episode=ep, new_status="READY_FOR_PAYMENT", actor=data["pharmacist"])
    assert ep.status == "READY_FOR_PAYMENT"


def test_batch_verification_success_and_failure(setup_domain):
    data = setup_domain
    sku = data["sku"]

    # Valid verification
    res = PosBatchVerificationService.verify_batch(
        tenant=data["tenant"], sku_id=sku.id, batch_number="B12345"
    )
    assert res["valid"]
    assert res["release_status"] == "RELEASED"

    # Invalid batch number
    res_bad = PosBatchVerificationService.verify_batch(
        tenant=data["tenant"], sku_id=sku.id, batch_number="INVALID_BATCH"
    )
    assert not res_bad["valid"]
    assert "not found" in res_bad["reason"]


def test_payment_orchestration_links_payment_without_inventory_deduction(setup_domain):
    data = setup_domain
    episode = data["episode"]
    episode.status = "READY_FOR_PAYMENT"
    episode.save()

    res = PosPaymentOrchestrationService.process_payment(
        episode=episode,
        tender_type="MPESA",
        paid_amount=Decimal("150.00"),
        payment_reference="MPESA-REF-999",
        cashier=data["cashier"],
    )

    assert res["success"]
    assert res["payment_status"] == "PAID"
    episode.refresh_from_db()
    assert episode.status == "PAID"
    assert episode.paid_amount == Decimal("150.00")

    # Verify no additional inventory ledger posting occurred during payment (only initial RECEIPT exists)
    ledger_entries = InventoryLedgerEntry.all_objects.filter(tenant=data["tenant"])
    assert ledger_entries.count() == 1


def test_partial_dispensing_and_repeat_eligibility(setup_domain):
    data = setup_domain
    episode = data["episode"]
    line = data["line"]

    res = PosPartialRepeatService.dispense_partial(
        episode=episode,
        dispensing_line_id=line.id,
        quantity_supplied=Decimal("10"),
        reason="Patient requested partial supply",
    )

    assert res["outstanding_balance"] == "20.0000"
    assert res["status"] == "PARTIALLY_SUPPLIED"

    repeat_info = PosPartialRepeatService.check_repeat_eligibility(
        tenant=data["tenant"], prescription_id=data["rx"].id
    )
    assert repeat_info["eligible"]
    assert repeat_info["repeats_remaining"] == 3


def test_controlled_medicine_verification(setup_domain):
    data = setup_domain
    episode = data["episode"]

    res = PosControlledMedicineService.verify_controlled_authority(
        episode=episode,
        practitioner_id=data["practitioner"].id,
        collector_id_number="ID-998877",
        witness=data["witness"],
    )

    assert res["verified"]
    episode.refresh_from_db()
    assert episode.controlled_authority_checked
    assert episode.collector_id_number == "ID-998877"
    assert episode.controlled_witness == data["witness"]


def test_counselling_recording(setup_domain):
    data = setup_domain
    episode = data["episode"]

    counselling = PosCounsellingService.record_counselling(
        episode=episode,
        pharmacist=data["pharmacist"],
        notes="Discussed taking with food.",
    )

    assert counselling.counselling_completed
    episode.refresh_from_db()
    assert episode.counselling_status == "COMPLETED"


def test_collection_confirms_supply_and_posts_inventory(setup_domain):
    data = setup_domain
    episode = data["episode"]
    episode.status = "PAID"
    episode.payment_status = "PAID"
    episode.save()

    supply = PosCollectionService.confirm_collection(
        episode=episode,
        collector_name="John Doe",
        collector_id_number="ID-12345",
        collector_phone="0712345678",
        collector_relationship="SELF",
        collection_proof_type="SIGNATURE",
        signature_ref="SIG-REF-001",
        actor=data["pharmacist"],
    )

    assert supply.status == "COMPLETE"
    episode.refresh_from_db()
    assert episode.status == "SUPPLIED"
    assert episode.collector_name == "John Doe"

    # Verify inventory ledger posting occurred NOW upon confirmed supply (1 receipt + 1 issue)
    ledger_entries = InventoryLedgerEntry.all_objects.filter(tenant=data["tenant"])
    assert ledger_entries.count() == 2
    entry = ledger_entries.first()
    assert entry.quantity_delta == Decimal("-30.0000")
    assert entry.entry_type == InventoryLedgerEntry.EntryType.ISSUE


def test_shift_operations_reconciliation(setup_domain):
    data = setup_domain
    tenant = data["tenant"]

    shift = PosShiftService.start_shift(
        tenant=tenant,
        shift_number="SHIFT-001",
        cashier=data["cashier"],
        pharmacist=data["pharmacist"],
        location=data["branch"],
        controlled_start_count=50,
    )
    assert shift.status == "OPEN"

    # End shift with matching count
    ended = PosShiftService.end_shift(shift=shift, controlled_end_count=50, declaration_notes="All clear")
    assert ended.status == "CLOSED"
    assert not ended.discrepancy_declared

    # Shift with mismatch
    shift2 = PosShiftService.start_shift(
        tenant=tenant,
        shift_number="SHIFT-002",
        cashier=data["cashier"],
        pharmacist=data["pharmacist"],
        location=data["branch"],
        controlled_start_count=50,
    )
    ended2 = PosShiftService.end_shift(shift=shift2, controlled_end_count=48, declaration_notes="Discrepancy found")
    assert ended2.discrepancy_declared
