from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.cds.models import (
    ActiveIngredient,
    ClinicalEvaluation,
    ClinicalFinding,
    ClinicalKnowledgeRelease,
    ClinicalKnowledgeRule,
    MedicineIngredient,
)
from apps.cds.services import ClinicalDecisionSupportService
from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.documents.models import StoredClinicalDocument
from apps.identity.models import User, UserRole
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry, InventoryLocation
from apps.inventory.services import InventoryLedgerService
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.notifications.models import NotificationOutbox
from apps.patients.models import PatientIdentifier
from apps.patients.services import PatientGovernanceService
from apps.practitioners.models import Practitioner
from apps.prescription.management.commands.check_clinical_dispensing_integrity import (
    Command as ClinicalIntegrityCommand,
)
from apps.prescription.models import (
    ClinicalWorkItem,
    DispensingEpisode,
    DispensingReversal,
    MedicineSupply,
    MedicineSupplyLine,
    PatientMedicationHistory,
    PatientReturn,
    PharmacistVerification,
    Prescription,
    PrescriptionItem,
    PrescriptionValidationFinding,
)
from apps.prescription.services.clinical_dispensing import (
    DispensingAllocationService,
    DispensingCheckService,
    DispensingEpisodeService,
    DispensingLabelService,
    DispensingPreparationService,
    DispensingReservationService,
    DispensingReversalService,
    MedicineSupplyService,
    PatientCounsellingService,
    PatientReturnService,
    PharmacistReviewService,
    PharmacistVerificationService,
    PrescriptionIntakeService,
    PrescriptionValidationService,
    RepeatDispensingService,
)
from apps.workflows.models import DomainEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def phase5_setup(clinical_setup, clinical_user):
    tenant = clinical_setup["tenant"]
    token = set_current_tenant_id(tenant.id)
    patient = clinical_setup["patient"]
    patient.patient_number = "PAT-PHASE5"
    patient.phone = "+254700000001"
    patient.email = "patient@example.test"
    patient.consent_status = "GRANTED"
    patient.save()
    practitioner = clinical_setup["practitioner"]
    practitioner.professional_name = "Dr David Otieno"
    practitioner.registration_number = "REG-PHASE5"
    practitioner.licensing_body = "Configured test authority"
    practitioner.licence_status = "VALID"
    practitioner.licence_issue_date = date.today() - timedelta(days=365)
    practitioner.licence_expiry_date = date.today() + timedelta(days=365)
    practitioner.prescribing_scope = ["GENERAL", "CONTROLLED"]
    practitioner.controlled_medicine_authority = True
    practitioner.organization = clinical_setup["organization"]
    practitioner.verification_state = "VERIFIED"
    practitioner.verified_by = clinical_user
    practitioner.verified_at = timezone.now()
    practitioner.save()
    role = UserRole.all_objects.get(user=clinical_user).role
    checker = User.objects.create_user(
        username="phase5-checker",
        password="test-password-strong",
        tenant=tenant,
    )
    UserRole.all_objects.create(
        tenant=tenant,
        user=checker,
        role=role,
    )
    dose_form = DoseForm.objects.create(code="PHASE5-TAB", name="Tablet")
    clinical_product = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant,
        code="CMP-PHASE5",
        canonical_name="Phase 5 test tablet",
        dose_form=dose_form,
        status="ACTIVE",
    )
    manufactured_product = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant,
        code="MMP-PHASE5",
        brand_name="PhaseFive",
        clinical_product=clinical_product,
        status="ACTIVE",
    )
    package = PackageDefinition.objects.create(
        code="PACK-PHASE5",
        description="Phase 5 dispensing unit",
        unit_of_measure="TABLET",
        is_dispensing_unit=True,
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant,
        sku_code="SKU-PHASE5",
        display_name="PhaseFive tablets",
        manufactured_product=manufactured_product,
        package_definition=package,
        status="ACTIVE",
    )
    inventory_location = InventoryLocation.all_objects.create(
        tenant=tenant,
        branch=clinical_setup["location"],
        location_code="PHASE5-VAULT",
        name="Phase 5 dispensing vault",
        location_type="CONTROLLED_VAULT",
        controlled_drug_capability=True,
    )
    quarantine_location = InventoryLocation.all_objects.create(
        tenant=tenant,
        branch=clinical_setup["location"],
        location_code="PHASE5-RETURNS",
        name="Phase 5 returns quarantine",
        location_type="QUARANTINE",
        quarantine_capability=True,
        returns_capability=True,
    )
    batch = InventoryBatch.all_objects.create(
        tenant=tenant,
        sku=sku,
        manufactured_product=manufactured_product,
        manufacturer_batch_number="PHASE5-BATCH-001",
        expiry_date=date.today() + timedelta(days=365),
        quality_status="RELEASED",
    )
    InventoryLedgerService.post_entry(
        tenant=tenant,
        branch=clinical_setup["location"],
        location=inventory_location,
        sku=sku,
        inventory_batch=batch,
        entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
        quantity_delta=100,
        unit="TABLET",
        base_quantity_delta=100,
        effective_timestamp=timezone.now(),
        source_document_type="PHASE5_TEST",
        source_document_id="PHASE5_TEST_RECEIPT",
        idempotency_key="phase5-test-receipt",
        actor=clinical_user,
    )
    release = ClinicalKnowledgeRelease.all_objects.create(
        tenant=tenant,
        code="PHASE5-TEST-RULES",
        version="1",
        source="Phase 5 test content",
        source_version="1",
        licence="Test only",
        effective_date=date.today(),
        is_active=True,
        content_classification="DEMONSTRATION",
        checksum_sha256="a" * 64,
    )
    ingredient = ActiveIngredient.all_objects.create(
        tenant=tenant,
        code="PHASE5-INGREDIENT",
        name="Phase 5 ingredient",
    )
    MedicineIngredient.all_objects.create(
        tenant=tenant,
        medicine=clinical_setup["medicine_a"],
        ingredient=ingredient,
    )
    try:
        yield {
            **clinical_setup,
            "user": clinical_user,
            "checker": checker,
            "sku": sku,
            "batch": batch,
            "inventory_location": inventory_location,
            "quarantine_location": quarantine_location,
            "release": release,
        }
    finally:
        reset_current_tenant_id(token)


def _receive(
    setup,
    number,
    *,
    controlled=False,
    practitioner=None,
    quantity="6",
    refills=0,
    minimum_repeat_interval_days=0,
):
    practitioner = practitioner or setup["practitioner"]
    return PrescriptionIntakeService.receive(
        tenant=setup["tenant"],
        actor=setup["user"],
        items=[
            {
                "canonical_medicine": setup["medicine_a"],
                "prescribed_sku": setup["sku"],
                "medication_name": "PhaseFive tablets",
                "prescribed_description_snapshot": "PhaseFive tablets",
                "active_ingredient_snapshot": [
                    {"code": "PHASE5-INGREDIENT", "name": "Phase 5 ingredient"}
                ],
                "strength_snapshot": "500 mg",
                "dosage_form_snapshot": "Tablet",
                "dosage_instruction": "Take one tablet once daily",
                "dose_amount": Decimal("1"),
                "dose_unit": "tablet",
                "frequency_per_day": Decimal("1"),
                "duration_days": int(Decimal(quantity)),
                "quantity": Decimal(quantity),
                "unit": "TABLET",
                "refills_authorized": refills,
                "repeats_remaining": refills,
                "minimum_repeat_interval_days": minimum_repeat_interval_days,
                "is_controlled": controlled,
                "route": "ORAL",
                "substitution_policy": "GENERIC_ALLOWED",
            }
        ],
        prescription_number=number,
        external_prescription_reference=f"EXT-{number}",
        patient=setup["patient"],
        practitioner=practitioner,
        organization=setup["organization"],
        location=setup["location"],
        prescribing_organization=setup["organization"],
        prescription_date=date.today(),
        prescription_type=(
            "CONTROLLED" if controlled else "REPEAT" if refills else "ACUTE"
        ),
        source_channel="ELECTRONIC",
        issued_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=30),
        is_controlled_medicine=controlled,
        repeat_authorization=bool(refills),
        repeats_allowed=refills,
        repeats_remaining=refills,
        metadata={"signature_evidence": f"SIG-{number}"},
    )


def _approve(setup, prescription):
    PrescriptionValidationService.validate(
        prescription=prescription,
        actor=setup["user"],
    )
    review = PharmacistReviewService.start(
        prescription=prescription,
        actor=setup["user"],
    )
    PharmacistReviewService.complete(
        review=review,
        actor=setup["user"],
        outcome="APPROVED",
    )
    return PharmacistVerificationService.verify(
        prescription=prescription,
        actor=setup["user"],
        idempotency_key=f"verify:{prescription.prescription_number}",
    )


def _prepare_episode(setup, prescription, quantity, *, key_suffix=""):
    episode = DispensingEpisodeService.create(
        prescription=prescription,
        branch=setup["location"],
        pharmacy_location=setup["inventory_location"],
        actor=setup["user"],
        idempotency_key=(
            f"episode:{prescription.prescription_number}:{key_suffix}"
        ),
    )
    item = PrescriptionItem.all_objects.get(prescription=prescription)
    DispensingReservationService.reserve(
        episode=episode,
        prescription_item=item,
        quantity=quantity,
        actor=setup["user"],
        idempotency_key=(
            f"reserve:{prescription.prescription_number}:{key_suffix}"
        ),
    )
    DispensingAllocationService.allocate(
        episode=episode,
        actor=setup["user"],
    )
    lines = DispensingPreparationService.prepare(
        episode=episode,
        actor=setup["user"],
    )
    for line in lines:
        DispensingLabelService.generate(
            dispensing_line=line,
            actor=setup["user"],
        )
    return episode, lines


def _check_and_counsel(setup, episode):
    checklist = {
        "patient": True,
        "medicine": True,
        "strength": True,
        "dosage_form": True,
        "quantity": True,
        "batch": True,
        "expiry": True,
        "instructions": True,
        "warnings": True,
        "package_integrity": True,
    }
    final_check = DispensingCheckService.check(
        episode=episode,
        actor=setup["checker"],
        checklist=checklist,
    )
    PatientCounsellingService.record(
        episode=episode,
        actor=setup["user"],
        counselling_required=True,
        counselling_completed=True,
        topics=["DOSAGE", "STORAGE", "ADHERENCE"],
        administration_instructions="Take exactly as directed.",
    )
    return final_check


def test_sensitive_identifier_is_protected_masked_and_audited(phase5_setup):
    identifier = PatientGovernanceService.add_identifier(
        patient=phase5_setup["patient"],
        actor=phase5_setup["user"],
        identifier_type="NATIONAL_ID",
        value="1234567890",
        verification_status="VERIFIED",
    )
    assert identifier.value == ""
    assert "1234567890" not in identifier.protected_value
    assert identifier.masked_value == "••••7890"
    assert (
        PatientGovernanceService.reveal_identifier(
            identifier=identifier,
            actor=phase5_setup["user"],
            reason="Identity reconciliation",
        )
        == "1234567890"
    )
    assert AuditEvent.all_objects.filter(
        action="PATIENT_IDENTIFIER_REVEALED",
        object_id=str(identifier.id),
    ).exists()


def test_expired_prescriber_fails_legal_validation(phase5_setup):
    expired = Practitioner.all_objects.create(
        tenant=phase5_setup["tenant"],
        first_name="Expired",
        last_name="Prescriber",
        professional_name="Expired Prescriber",
        registration_number="REG-EXPIRED-PHASE5",
        licensing_body="Configured test authority",
        licence_status="VALID",
        licence_issue_date=date.today() - timedelta(days=730),
        licence_expiry_date=date.today() - timedelta(days=1),
        prescribing_scope=["GENERAL"],
        organization=phase5_setup["organization"],
        verification_state="VERIFIED",
        status="ACTIVE",
    )
    prescription = _receive(
        phase5_setup,
        "RX-PHASE5-EXPIRED",
        practitioner=expired,
    )
    result = PrescriptionValidationService.validate(
        prescription=prescription,
        actor=phase5_setup["user"],
    )
    assert result.legal_validation_state == "FAILED"
    assert PrescriptionValidationFinding.all_objects.filter(
        prescription=prescription,
        finding_code="PRESCRIBER_LICENCE_EXPIRED",
        severity="CRITICAL",
    ).exists()


def test_critical_finding_requires_authorized_override(phase5_setup):
    ClinicalKnowledgeRule.all_objects.create(
        release=phase5_setup["release"],
        tenant=phase5_setup["tenant"],
        rule_id="PHASE5-CONTRAINDICATION",
        rule_version="1",
        rule_type="CONDITION",
        primary_code="PHASE5-INGREDIENT",
        severity="CRITICAL",
        evidence_summary="Test evidence",
        explanation="Configured test contraindication",
        recommended_action="Resolve before verification",
        override_policy="PHARMACIST",
        criteria={"demo_match": True},
        effective_date=date.today(),
    )
    prescription = _receive(phase5_setup, "RX-PHASE5-OVERRIDE")
    PrescriptionValidationService.validate(
        prescription=prescription,
        actor=phase5_setup["user"],
    )
    review = PharmacistReviewService.start(
        prescription=prescription,
        actor=phase5_setup["user"],
    )
    with pytest.raises(ValidationError):
        PharmacistReviewService.complete(
            review=review,
            actor=phase5_setup["user"],
            outcome="APPROVED",
        )
    finding = ClinicalFinding.all_objects.get(prescription=prescription)
    PharmacistReviewService.resolve_finding(
        finding=finding,
        actor=phase5_setup["user"],
        resolution_status="OVERRIDDEN",
        reason="Patient-specific risk-benefit decision",
        clinical_justification="Documented clinical monitoring plan.",
    )
    PharmacistReviewService.complete(
        review=review,
        actor=phase5_setup["user"],
        outcome="APPROVED",
    )
    verification = PharmacistVerificationService.verify(
        prescription=prescription,
        actor=phase5_setup["user"],
        idempotency_key="verify:RX-PHASE5-OVERRIDE",
    )
    verification.clinical_justification = "Mutation is prohibited"
    with pytest.raises(ValidationError, match="immutable"):
        verification.save()


def test_integrity_checker_detects_verification_and_state_corruption(
    phase5_setup,
):
    prescription = _receive(
        phase5_setup,
        "RX-PHASE5-INTEGRITY-CORRUPTION",
    )
    verification = _approve(phase5_setup, prescription)
    evaluation = ClinicalEvaluation.all_objects.filter(
        tenant=phase5_setup["tenant"],
        prescription=prescription,
    ).latest("created_at")
    ClinicalFinding.all_objects.create(
        tenant=phase5_setup["tenant"],
        evaluation=evaluation,
        patient=phase5_setup["patient"],
        prescription=prescription,
        prescription_item=prescription.items.get(),
        affected_medicine=phase5_setup["medicine_a"],
        rule_id="PHASE5-INTEGRITY-CRITICAL",
        rule_version="1",
        rule_type="CONTRAINDICATION",
        source="Phase 5 integrity test",
        source_version="1",
        effective_date=date.today(),
        severity="CRITICAL",
        evidence_summary="Integrity test evidence",
        explanation="Unresolved critical finding",
        recommended_action="Block verification",
        override_policy="PROHIBITED",
    )
    PharmacistVerification.all_objects.filter(
        tenant=phase5_setup["tenant"],
        id=verification.id,
    ).update(verification_checks={})
    Prescription.all_objects.filter(
        tenant=phase5_setup["tenant"],
        id=prescription.id,
    ).update(pharmacist_verification_state="REVOKED")

    issue_codes = {
        issue["code"]
        for issue in ClinicalIntegrityCommand()._check_tenant(
            phase5_setup["tenant"]
        )
    }
    assert {
        "VERIFICATION_WITH_UNRESOLVED_CRITICAL_FINDING",
        "INVALID_PRESCRIBER_AT_VERIFICATION",
        "PHARMACIST_AUTHORITY_EVIDENCE_MISSING",
        "INVALID_PRESCRIPTION_STATE",
    }.issubset(issue_codes)


def test_supply_is_batch_exact_partial_and_idempotent(phase5_setup):
    prescription = _receive(phase5_setup, "RX-PHASE5-SUPPLY")
    _approve(phase5_setup, prescription)
    episode, lines = _prepare_episode(phase5_setup, prescription, Decimal("6"))
    with pytest.raises(ValidationError, match="preparer"):
        DispensingCheckService.check(
            episode=episode,
            actor=phase5_setup["user"],
            checklist={
                key: True
                for key in DispensingCheckService.REQUIRED_CHECKS
            },
        )
    _check_and_counsel(phase5_setup, episode)
    line = lines[0]
    first = MedicineSupplyService.supply(
        episode=episode,
        actor=phase5_setup["user"],
        idempotency_key="supply:RX-PHASE5-SUPPLY:1",
        line_quantities={str(line.id): Decimal("3")},
        partial_reason="PATIENT_REQUEST",
        next_eligible_date=date.today() + timedelta(days=1),
    )
    issue_count = InventoryLedgerEntry.all_objects.filter(
        source_document_type="MEDICINE_SUPPLY",
        source_document_id=str(first.id),
    ).count()
    retry = MedicineSupplyService.supply(
        episode=episode,
        actor=phase5_setup["user"],
        idempotency_key="supply:RX-PHASE5-SUPPLY:1",
        line_quantities={str(line.id): Decimal("3")},
    )
    assert retry.id == first.id
    assert (
        InventoryLedgerEntry.all_objects.filter(
            source_document_type="MEDICINE_SUPPLY",
            source_document_id=str(first.id),
        ).count()
        == issue_count
        == 1
    )
    first_line = MedicineSupplyLine.all_objects.get(supply=first)
    assert first_line.inventory_batch_id == phase5_setup["batch"].id
    assert first_line.inventory_issue.base_quantity_delta == Decimal("-3")
    assert first_line.outstanding_quantity == Decimal("3")
    assert PatientMedicationHistory.all_objects.filter(
        medicine_supply_line=first_line,
        source="MEDICINE_SUPPLY",
        quantity=Decimal("3"),
    ).exists()
    episode.refresh_from_db()
    assert episode.status == "PARTIALLY_SUPPLIED"
    second = MedicineSupplyService.supply(
        episode=episode,
        actor=phase5_setup["user"],
        idempotency_key="supply:RX-PHASE5-SUPPLY:2",
        line_quantities={str(line.id): Decimal("3")},
    )
    episode.refresh_from_db()
    prescription.refresh_from_db()
    assert second.status == "COMPLETE"
    assert episode.status == "SUPPLIED"
    assert prescription.status == "SUPPLIED"
    assert PrescriptionItem.all_objects.get(
        prescription=prescription
    ).quantity_supplied_total == Decimal("6")
    document_types = {
        document.metadata.get("document_type")
        for document in StoredClinicalDocument.all_objects.filter(
            tenant=phase5_setup["tenant"],
            patient=phase5_setup["patient"],
        )
    }
    assert {
        "PRESCRIPTION_INTAKE_RECORD",
        "CLINICAL_REVIEW_SUMMARY",
        "DISPENSING_WORKSHEET",
        "DISPENSING_LABEL",
        "PATIENT_MEDICATION_INFORMATION_SHEET",
        "COUNSELLING_ACKNOWLEDGEMENT",
        "PARTIAL_DISPENSING_BALANCE_RECORD",
    }.issubset(document_types)


def test_reversal_and_return_do_not_restock_saleable_inventory(phase5_setup):
    prescription = _receive(phase5_setup, "RX-PHASE5-RETURN", quantity="2")
    _approve(phase5_setup, prescription)
    episode, lines = _prepare_episode(phase5_setup, prescription, Decimal("2"))
    _check_and_counsel(phase5_setup, episode)
    supply = MedicineSupplyService.supply(
        episode=episode,
        actor=phase5_setup["user"],
        idempotency_key="supply:RX-PHASE5-RETURN",
        line_quantities={str(lines[0].id): Decimal("2")},
    )
    supply_line = MedicineSupplyLine.all_objects.get(supply=supply)
    ledger_count = InventoryLedgerEntry.all_objects.count()
    reversal = DispensingReversalService.reverse(
        supply_line=supply_line,
        actor=phase5_setup["user"],
        reason="Wrong patient instruction recorded",
        idempotency_key="reversal:RX-PHASE5-RETURN",
        quantity=Decimal("1"),
        physically_returned=True,
        return_condition="UNOPENED",
    )
    assert reversal.quantity == Decimal("1")
    assert InventoryLedgerEntry.all_objects.count() == ledger_count
    assert PatientMedicationHistory.all_objects.filter(
        medicine_supply_line=supply_line,
        source__startswith="DISPENSING_REVERSAL:",
        status="REVERSED",
    ).exists()
    second_reversal = DispensingReversalService.reverse(
        supply_line=supply_line,
        actor=phase5_setup["user"],
        reason="Complete the correction",
        idempotency_key="reversal:RX-PHASE5-RETURN:2",
        quantity=Decimal("1"),
        physically_returned=True,
        return_condition="UNOPENED",
    )
    assert second_reversal.id != reversal.id
    assert DispensingReversal.all_objects.filter(supply=supply).count() == 2
    assert PatientMedicationHistory.all_objects.filter(
        medicine_supply_line=supply_line,
        source__startswith="DISPENSING_REVERSAL:",
    ).count() == 2
    supply.refresh_from_db()
    assert supply.status == "REVERSED"
    assert PrescriptionItem.all_objects.get(
        prescription=prescription
    ).quantity_supplied_total == Decimal("0")
    patient_return = PatientReturnService.receive(
        supply=supply,
        actor=phase5_setup["user"],
        quarantine_location=phase5_setup["quarantine_location"],
        reason="Patient returned unopened medicine",
        lines=[
            {
                "supply_line_id": supply_line.id,
                "quantity": Decimal("1"),
                "condition": "UNOPENED",
            }
        ],
        idempotency_key="return:RX-PHASE5-RETURN",
    )
    PatientReturnService.inspect(
        patient_return=patient_return,
        actor=phase5_setup["checker"],
        quality_decision="RETAIN_IN_QUARANTINE",
    )
    patient_return.refresh_from_db()
    assert patient_return.status == "INSPECTED"
    assert patient_return.quality_decision == "RETAIN_IN_QUARANTINE"
    assert InventoryLedgerEntry.all_objects.count() == ledger_count
    document_types = {
        document.metadata.get("document_type")
        for document in StoredClinicalDocument.all_objects.filter(
            tenant=phase5_setup["tenant"],
            patient=phase5_setup["patient"],
        )
    }
    assert "DISPENSING_REVERSAL_RECORD" in document_types
    assert "PATIENT_RETURN_RECEIPT" in document_types


def test_material_change_revokes_verification_and_emits_once(phase5_setup):
    prescription = _receive(phase5_setup, "RX-PHASE5-STALE")
    verification = _approve(phase5_setup, prescription)
    before = DomainEvent.all_objects.filter(
        event_type="PrescriptionVerificationRevoked",
        aggregate_id=prescription.id,
    ).count()
    item = PrescriptionItem.all_objects.get(prescription=prescription)
    item.quantity = Decimal("7")
    item.save()
    verification.refresh_from_db()
    prescription.refresh_from_db()
    assert verification.revoked_at is not None
    assert prescription.pharmacist_verification_state == "REVOKED"
    assert (
        DomainEvent.all_objects.filter(
            event_type="PrescriptionVerificationRevoked",
            aggregate_id=prescription.id,
        ).count()
        == before + 1
    )


def test_patient_list_applies_least_privilege(
    phase5_setup,
    cashier_user,
    django_assert_max_num_queries,
):
    PatientGovernanceService.add_identifier(
        patient=phase5_setup["patient"],
        actor=phase5_setup["user"],
        identifier_type="PASSPORT",
        value="A1234567",
    )
    client = APIClient()
    client.force_authenticate(cashier_user)
    with django_assert_max_num_queries(5):
        response = client.get(
            "/api/patients/",
            HTTP_X_TENANT_ID=str(phase5_setup["tenant"].id),
        )
    assert response.status_code == 200
    patient = next(
        row
        for row in response.data
        if row["id"] == str(phase5_setup["patient"].id)
    )
    assert patient["phone"] is None
    assert patient["email"] is None
    assert patient["identifiers"] == []
    assert patient["allergies"] == []
    assert patient["medication_statements"] == []
    assert patient["clinical_summary"] is None
    assert patient["metadata"] is None
    identifier_response = client.get(
        f"/api/patients/{phase5_setup['patient'].id}/identifiers/",
        HTTP_X_TENANT_ID=str(phase5_setup["tenant"].id),
    )
    history_response = client.get(
        f"/api/patients/{phase5_setup['patient'].id}/medication-history/",
        HTTP_X_TENANT_ID=str(phase5_setup["tenant"].id),
    )
    assert identifier_response.status_code == 403
    assert history_response.status_code == 403


def test_dur_checks_are_configurable_versioned_and_deduplicated(phase5_setup):
    for rule_id, rule_type, criteria in (
        (
            "PHASE5-DOSE",
            "DOSE_TOO_HIGH",
            {"maximum_daily_dose": "0.5"},
        ),
        (
            "PHASE5-FREQUENCY",
            "FREQUENCY_TOO_HIGH",
            {"maximum_frequency_per_day": "0.5"},
        ),
        (
            "PHASE5-WEIGHT",
            "WEIGHT_BASED_DOSE",
            {"requires_weight": True},
        ),
    ):
        ClinicalKnowledgeRule.all_objects.create(
            release=phase5_setup["release"],
            tenant=phase5_setup["tenant"],
            rule_id=rule_id,
            rule_version="2026.1",
            rule_type=rule_type,
            primary_code="PHASE5-INGREDIENT",
            severity="HIGH",
            evidence_summary="Configured test evidence",
            explanation=f"Configured {rule_type} rule",
            recommended_action="Pharmacist review required",
            override_policy="PHARMACIST",
            criteria=criteria,
            effective_date=date.today(),
        )
    prescription = _receive(phase5_setup, "RX-PHASE5-DUR")
    evaluation = ClinicalDecisionSupportService.evaluate(
        prescription=prescription,
        actor=phase5_setup["user"],
    )
    findings = ClinicalFinding.all_objects.filter(evaluation=evaluation)
    assert findings.count() == 3
    assert set(findings.values_list("rule_version", flat=True)) == {"2026.1"}
    assert findings.filter(
        rule_id="PHASE5-WEIGHT",
        rule_type="INSUFFICIENT_DATA",
    ).exists()
    assert findings.values(
        "rule_id",
        "rule_version",
        "prescription_item_id",
        "interacting_factor",
    ).distinct().count() == findings.count()


def test_duplicate_therapy_detects_repeated_ingredient(phase5_setup):
    ClinicalKnowledgeRule.all_objects.create(
        release=phase5_setup["release"],
        tenant=phase5_setup["tenant"],
        rule_id="PHASE5-DUPLICATE",
        rule_version="1",
        rule_type="DUPLICATE_THERAPY",
        primary_code="PHASE5-INGREDIENT",
        severity="HIGH",
        evidence_summary="Configured duplicate-therapy evidence",
        explanation="Repeated ingredient requires review",
        recommended_action="Confirm therapeutic intent",
        override_policy="PHARMACIST",
        effective_date=date.today(),
    )
    prescription = _receive(phase5_setup, "RX-PHASE5-DUPLICATE")
    PrescriptionItem.all_objects.create(
        tenant=phase5_setup["tenant"],
        prescription=prescription,
        canonical_medicine=phase5_setup["medicine_a"],
        prescribed_sku=phase5_setup["sku"],
        medication_name="PhaseFive duplicate tablets",
        prescribed_description_snapshot="PhaseFive duplicate tablets",
        strength_snapshot="500 mg",
        dosage_form_snapshot="Tablet",
        dosage_instruction="Take one tablet once daily",
        dose_amount=Decimal("1"),
        dose_unit="tablet",
        frequency_per_day=Decimal("1"),
        duration_days=6,
        quantity=Decimal("6"),
        unit="TABLET",
        route="ORAL",
    )
    evaluation = ClinicalDecisionSupportService.evaluate(
        prescription=prescription,
        actor=phase5_setup["user"],
    )
    assert ClinicalFinding.all_objects.filter(
        evaluation=evaluation,
        rule_id="PHASE5-DUPLICATE",
        rule_type="DUPLICATE_THERAPY",
    ).count() == 1


def test_repeat_queue_interval_and_repeat_document(
    phase5_setup,
    cashier_user,
):
    prescription = _receive(
        phase5_setup,
        "RX-PHASE5-REPEAT",
        refills=1,
        minimum_repeat_interval_days=30,
    )
    _approve(phase5_setup, prescription)
    episode, lines = _prepare_episode(
        phase5_setup,
        prescription,
        Decimal("6"),
        key_suffix="initial",
    )
    _check_and_counsel(phase5_setup, episode)
    MedicineSupplyService.supply(
        episode=episode,
        actor=phase5_setup["user"],
        idempotency_key="supply:RX-PHASE5-REPEAT:initial",
        line_quantities={str(lines[0].id): Decimal("6")},
    )
    item = PrescriptionItem.all_objects.get(prescription=prescription)
    assert item.repeats_remaining == 1
    assert item.earliest_refill_date == date.today() + timedelta(days=30)
    assert ClinicalWorkItem.all_objects.filter(
        prescription=prescription,
        queue_type="REPEAT_DUE",
        status="OPEN",
    ).exists()
    with pytest.raises(ValidationError, match="earlier"):
        RepeatDispensingService.validate(
            prescription_item=item,
            actor=cashier_user,
        )
    assert ClinicalWorkItem.all_objects.filter(
        prescription=prescription,
        queue_type="EARLY_REPEAT_REVIEW",
        status="OPEN",
    ).exists()
    assert NotificationOutbox.all_objects.filter(
        tenant=phase5_setup["tenant"],
        template_code="REPEAT_TOO_EARLY",
    ).exists()
    item.earliest_refill_date = date.today()
    item.save()
    repeat_episode, repeat_lines = _prepare_episode(
        phase5_setup,
        prescription,
        Decimal("6"),
        key_suffix="repeat-1",
    )
    _check_and_counsel(phase5_setup, repeat_episode)
    MedicineSupplyService.supply(
        episode=repeat_episode,
        actor=phase5_setup["user"],
        idempotency_key="supply:RX-PHASE5-REPEAT:repeat-1",
        line_quantities={str(repeat_lines[0].id): Decimal("6")},
    )
    item.refresh_from_db()
    prescription.refresh_from_db()
    assert item.quantity_supplied_total == Decimal("12")
    assert item.repeats_remaining == 0
    assert prescription.repeats_remaining == 0
    assert StoredClinicalDocument.all_objects.filter(
        tenant=phase5_setup["tenant"],
        metadata__document_type="REPEAT_DISPENSING_RECORD",
    ).exists()


def test_controlled_supply_closes_queue_and_generates_register_document(
    phase5_setup,
):
    PatientGovernanceService.add_identifier(
        patient=phase5_setup["patient"],
        actor=phase5_setup["user"],
        identifier_type="NATIONAL_ID",
        value="CONTROLLED-IDENTITY-1",
        verification_status="VERIFIED",
    )
    prescription = _receive(
        phase5_setup,
        "RX-PHASE5-CONTROLLED",
        controlled=True,
        quantity="2",
    )
    PrescriptionValidationService.validate(
        prescription=prescription,
        actor=phase5_setup["user"],
    )
    assert ClinicalWorkItem.all_objects.filter(
        prescription=prescription,
        queue_type="CONTROLLED_MEDICINE_REVIEW",
        status="OPEN",
    ).exists()
    review = PharmacistReviewService.start(
        prescription=prescription,
        actor=phase5_setup["user"],
    )
    PharmacistReviewService.complete(
        review=review,
        actor=phase5_setup["user"],
        outcome="APPROVED",
    )
    PharmacistVerificationService.verify(
        prescription=prescription,
        actor=phase5_setup["user"],
        idempotency_key="verify:RX-PHASE5-CONTROLLED",
    )
    assert not ClinicalWorkItem.all_objects.filter(
        prescription=prescription,
        queue_type="CONTROLLED_MEDICINE_REVIEW",
        status="OPEN",
    ).exists()
    episode, lines = _prepare_episode(
        phase5_setup,
        prescription,
        Decimal("2"),
        key_suffix="controlled",
    )
    _check_and_counsel(phase5_setup, episode)
    MedicineSupplyService.supply(
        episode=episode,
        actor=phase5_setup["user"],
        idempotency_key="supply:RX-PHASE5-CONTROLLED",
        line_quantities={str(lines[0].id): Decimal("2")},
    )
    assert StoredClinicalDocument.all_objects.filter(
        tenant=phase5_setup["tenant"],
        metadata__document_type="CONTROLLED_MEDICINE_SUPPLY_RECORD",
    ).exists()
    assert DomainEvent.all_objects.filter(
        event_type="ControlledMedicineSupplied",
        aggregate_id=prescription.id,
    ).count() == 1


def test_work_queue_api_is_role_and_branch_aware_with_bounded_queries(
    phase5_setup,
    cashier_user,
    django_assert_max_num_queries,
):
    prescription = _receive(phase5_setup, "RX-PHASE5-QUEUE")
    client = APIClient()
    client.force_authenticate(cashier_user)
    with django_assert_max_num_queries(5):
        denied_queue = client.get(
            "/api/clinical/work-items/",
            HTTP_X_TENANT_ID=str(phase5_setup["tenant"].id),
        )
    assert denied_queue.status_code == 200
    assert denied_queue.data == []
    clinical_detail = client.get(
        f"/api/prescriptions/{prescription.id}/findings/",
        HTTP_X_TENANT_ID=str(phase5_setup["tenant"].id),
    )
    assert clinical_detail.status_code == 403
    client.force_authenticate(phase5_setup["user"])
    with django_assert_max_num_queries(5):
        response = client.get(
            "/api/clinical/work-items/",
            {
                "branch": str(phase5_setup["location"].id),
                "queue_type": "LEGAL_VALIDATION",
            },
            HTTP_X_TENANT_ID=str(phase5_setup["tenant"].id),
        )
    assert response.status_code == 200
    assert len(response.data) == 1
    assert str(response.data[0]["prescription"]) == str(prescription.id)
    assert str(response.data[0]["branch"]) == str(phase5_setup["location"].id)
    malformed = client.get(
        "/api/clinical/work-items/",
        {"branch": "not-a-uuid"},
        HTTP_X_TENANT_ID=str(phase5_setup["tenant"].id),
    )
    assert malformed.status_code == 400


def test_phase5_read_paths_have_bounded_query_counts(
    phase5_setup,
    django_assert_max_num_queries,
):
    prescription = _receive(
        phase5_setup,
        "RX-PHASE5-QUERY-BOUNDS",
        controlled=True,
        refills=1,
    )
    ClinicalWorkItem.all_objects.bulk_create(
        [
            ClinicalWorkItem(
                tenant=phase5_setup["tenant"],
                queue_type=queue_type,
                prescription=prescription,
                branch=phase5_setup["location"],
                required_capability=required_capability,
            )
            for queue_type, required_capability in (
                ("CLINICAL_REVIEW", "prescriptions.clinical_review"),
                ("READY_FOR_DISPENSING", "dispensing.reserve"),
                ("REPEAT_DUE", "dispensing.repeat.authorize"),
                (
                    "CONTROLLED_MEDICINE_REVIEW",
                    "prescriptions.controlled_verify",
                ),
            )
        ]
    )
    client = APIClient()
    client.force_authenticate(phase5_setup["user"])
    headers = {"HTTP_X_TENANT_ID": str(phase5_setup["tenant"].id)}

    endpoints = (
        ("/api/prescriptions/", 5),
        (f"/api/prescriptions/{prescription.id}/", 5),
        (f"/api/prescriptions/{prescription.id}/findings/", 8),
        (
            f"/api/patients/{phase5_setup['patient'].id}/medication-history/",
            8,
        ),
        ("/api/clinical/work-items/?queue_type=CLINICAL_REVIEW", 5),
        ("/api/clinical/work-items/?queue_type=READY_FOR_DISPENSING", 5),
        ("/api/clinical/work-items/?queue_type=REPEAT_DUE", 5),
        (
            "/api/clinical/work-items/?queue_type=CONTROLLED_MEDICINE_REVIEW",
            5,
        ),
    )
    for endpoint, query_limit in endpoints:
        with django_assert_max_num_queries(query_limit):
            response = client.get(endpoint, **headers)
        assert response.status_code == 200

    with django_assert_max_num_queries(30):
        call_command(
            "check_clinical_dispensing_integrity",
            tenant=phase5_setup["tenant"].slug,
            verbosity=0,
        )


def test_phase5_seed_is_idempotent_and_integrity_clean(db):
    call_command("seed_clinical_dispensing", tenant="phase5-seed-test", verbosity=0)
    first = {
        "prescriptions": Prescription.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "episodes": DispensingEpisode.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "identifiers": PatientIdentifier.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "returns": PatientReturn.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "supplies": MedicineSupply.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "findings": ClinicalFinding.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "work_items": ClinicalWorkItem.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "reversals": DispensingReversal.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "documents": StoredClinicalDocument.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "notifications": NotificationOutbox.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "events": DomainEvent.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
    }
    call_command("seed_clinical_dispensing", tenant="phase5-seed-test", verbosity=0)
    second = {
        "prescriptions": Prescription.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "episodes": DispensingEpisode.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "identifiers": PatientIdentifier.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "returns": PatientReturn.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "supplies": MedicineSupply.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "findings": ClinicalFinding.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "work_items": ClinicalWorkItem.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "reversals": DispensingReversal.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "documents": StoredClinicalDocument.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "notifications": NotificationOutbox.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
        "events": DomainEvent.all_objects.filter(
            tenant__slug="phase5-seed-test"
        ).count(),
    }
    assert second == first
    call_command(
        "check_clinical_dispensing_integrity",
        tenant="phase5-seed-test",
        verbosity=0,
    )
