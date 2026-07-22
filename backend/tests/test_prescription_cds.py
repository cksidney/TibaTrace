from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from apps.cds.models import (
    ActiveIngredient,
    ClinicalKnowledgeRelease,
    ClinicalKnowledgeRule,
    ClinicalOverride,
    MedicineIngredient,
)
from apps.cds.services import ClinicalDecisionSupportService
from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.patients.models import PatientAllergy
from apps.prescription.models import Prescription, PrescriptionDispense, PrescriptionItem, PrescriptionWorkflowEvent
from apps.prescription.services.dispensing_engine import DispensingEngine
from apps.prescription.services.workflow import PrescriptionWorkflowError, PrescriptionWorkflowService

pytestmark = pytest.mark.django_db


def test_clinical_knowledge_manager_fails_closed_and_allows_explicit_global_scope(clinical_setup):
    release = _release(clinical_setup)
    assert ClinicalKnowledgeRelease.objects.count() == 0
    assert ClinicalKnowledgeRule.objects.count() == 0
    token = set_current_tenant_id(clinical_setup["tenant"].id)
    try:
        assert ClinicalKnowledgeRelease.objects.filter(id=release.id).exists()
    finally:
        reset_current_tenant_id(token)


def test_tenant_knowledge_release_precedes_newer_global_release(clinical_setup):
    tenant_release = _release(clinical_setup)
    ClinicalKnowledgeRelease.all_objects.create(
        tenant=None,
        is_global=True,
        code="GLOBAL-DEMO-KNOWLEDGE",
        version="9999",
        source="DawaTrace global test content",
        source_version="9999",
        licence="Internal demonstration only",
        effective_date=date.today(),
        is_active=True,
        content_classification="DEMONSTRATION",
        checksum_sha256="b" * 64,
    )
    selected = ClinicalDecisionSupportService._release(clinical_setup["tenant"].id)
    assert selected.id == tenant_release.id


def _prescription(setup, *, two_items=False):
    prescription = Prescription.all_objects.create(
        tenant=setup["tenant"],
        patient=setup["patient"],
        practitioner=setup["practitioner"],
        organization=setup["organization"],
        location=setup["location"],
        prescription_number=f"RX-{Prescription.all_objects.count() + 1}",
    )
    item_a = PrescriptionItem.all_objects.create(
        tenant=setup["tenant"],
        prescription=prescription,
        canonical_medicine=setup["medicine_a"],
        medication_name=setup["medicine_a"].generic_name,
        dosage_instruction="One daily",
        quantity="10",
    )
    if two_items:
        PrescriptionItem.all_objects.create(
            tenant=setup["tenant"],
            prescription=prescription,
            canonical_medicine=setup["medicine_b"],
            medication_name=setup["medicine_b"].generic_name,
            dosage_instruction="One daily",
            quantity="5",
        )
    return prescription, item_a


def _release(setup):
    return ClinicalKnowledgeRelease.all_objects.create(
        tenant=setup["tenant"],
        code="DEMO-KNOWLEDGE",
        version="1",
        source="DawaTrace test content",
        source_version="1",
        licence="Internal demonstration only",
        effective_date=date.today(),
        is_active=True,
        content_classification="DEMONSTRATION",
        checksum_sha256="a" * 64,
    )


def _ingredient(setup, medicine, code):
    ingredient = ActiveIngredient.all_objects.filter(tenant=setup["tenant"], code=code).first()
    if not ingredient:
        ingredient = ActiveIngredient.all_objects.create(tenant=setup["tenant"], code=code, name=code)
    MedicineIngredient.all_objects.create(
        tenant=setup["tenant"], medicine=medicine, ingredient=ingredient
    )
    return ingredient


def _rule(release, *, rule_type="DRUG_DRUG", primary="ING-A", factor="ING-B", severity="BLOCK", policy="PHARMACIST"):
    return ClinicalKnowledgeRule.all_objects.create(
        release=release,
        tenant=release.tenant,
        rule_id=f"{rule_type}-{ClinicalKnowledgeRule.all_objects.count() + 1}",
        rule_version="1",
        rule_type=rule_type,
        primary_code=primary,
        interacting_code=factor,
        severity=severity,
        evidence_summary="Demonstration evidence only",
        explanation="Demonstration clinical rule",
        recommended_action="Refer to an authorized clinician",
        override_policy=policy,
        effective_date=date.today(),
    )


def test_missing_knowledge_is_not_pass(clinical_setup, clinical_user):
    prescription, _ = _prescription(clinical_setup)
    result = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=clinical_user)
    assert result.status == "KNOWLEDGE_UNAVAILABLE"
    assert result.error_code == "NO_ACTIVE_KNOWLEDGE_RELEASE"


def test_empty_active_release_evaluates_pass(clinical_setup, clinical_user):
    _release(clinical_setup)
    prescription, _ = _prescription(clinical_setup)
    result = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=clinical_user)
    assert result.status == "PASS"


def test_drug_interaction_creates_source_attributed_block(clinical_setup, clinical_user):
    release = _release(clinical_setup)
    _ingredient(clinical_setup, clinical_setup["medicine_a"], "ING-A")
    _ingredient(clinical_setup, clinical_setup["medicine_b"], "ING-B")
    _rule(release)
    prescription, _ = _prescription(clinical_setup, two_items=True)
    result = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=clinical_user)
    assert result.status == "BLOCK"
    finding = result.findings.model.all_objects.get(evaluation=result)
    assert finding.source == release.source
    assert finding.rule_version == "1"
    assert finding.override_policy == "PHARMACIST"


def test_allergy_rule_uses_patient_context(clinical_setup, clinical_user):
    release = _release(clinical_setup)
    _ingredient(clinical_setup, clinical_setup["medicine_a"], "PENICILLIN")
    _rule(release, rule_type="ALLERGY", primary="PENICILLIN", factor="", severity="BLOCK")
    PatientAllergy.all_objects.create(
        tenant=clinical_setup["tenant"],
        patient=clinical_setup["patient"],
        allergen_name="Penicillin",
        allergen_code="PENICILLIN",
        severity="HARD_STOP",
    )
    prescription, _ = _prescription(clinical_setup)
    result = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=clinical_user)
    assert result.status == "BLOCK"
    assert result.findings.model.all_objects.get(evaluation=result).rule_type == "ALLERGY"


def test_duplicate_therapy_preserves_ingredient_multiplicity(clinical_setup, clinical_user):
    release = _release(clinical_setup)
    _ingredient(clinical_setup, clinical_setup["medicine_a"], "CLASS-X")
    _ingredient(clinical_setup, clinical_setup["medicine_b"], "CLASS-X")
    _rule(release, rule_type="DUPLICATE_THERAPY", primary="CLASS-X", factor="", severity="WARNING")
    prescription, _ = _prescription(clinical_setup, two_items=True)
    result = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=clinical_user)
    assert result.status == "WARNING"


def test_provider_exception_becomes_error_not_pass(clinical_setup, clinical_user):
    _release(clinical_setup)
    prescription, _ = _prescription(clinical_setup)

    class BrokenProvider:
        def __getattr__(self, name):
            def fail(context):
                raise RuntimeError("external detail must not escape")
            return fail

    result = ClinicalDecisionSupportService.evaluate(
        prescription=prescription, actor=clinical_user, provider=BrokenProvider()
    )
    assert result.status == "ERROR"
    assert result.error_detail == "Clinical knowledge provider evaluation failed."


def test_cds_override_requires_reason_and_capability(clinical_setup, clinical_user, cashier_user):
    release = _release(clinical_setup)
    _ingredient(clinical_setup, clinical_setup["medicine_a"], "ING-A")
    _ingredient(clinical_setup, clinical_setup["medicine_b"], "ING-B")
    _rule(release)
    prescription, _ = _prescription(clinical_setup, two_items=True)
    evaluation = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=clinical_user)
    finding = evaluation.findings.model.all_objects.get(evaluation=evaluation)
    with pytest.raises(ValidationError):
        ClinicalOverride.all_objects.create(
            tenant=clinical_setup["tenant"], finding=finding, prescription=prescription,
            authorized_by=clinical_user, reason=""
        )
    with pytest.raises(ValidationError):
        ClinicalOverride.all_objects.create(
            tenant=clinical_setup["tenant"], finding=finding, prescription=prescription,
            authorized_by=cashier_user, reason="Reviewed"
        )
    override = ClinicalOverride.all_objects.create(
        tenant=clinical_setup["tenant"], finding=finding, prescription=prescription,
        authorized_by=clinical_user, reason="Clinical rationale recorded"
    )
    assert override.reason


def test_prescription_cannot_skip_clinical_review(clinical_setup, clinical_user):
    prescription, _ = _prescription(clinical_setup)
    with pytest.raises(PrescriptionWorkflowError):
        PrescriptionWorkflowService.transition(
            prescription_id=prescription.id,
            tenant_id=clinical_setup["tenant"].id,
            actor=clinical_user,
            target_state="PAID",
            payment_reference="PAY-1",
        )


def test_cashier_cannot_start_clinical_review(clinical_setup, cashier_user):
    prescription, _ = _prescription(clinical_setup)
    with pytest.raises(PermissionError):
        PrescriptionWorkflowService.transition(
            prescription_id=prescription.id,
            tenant_id=clinical_setup["tenant"].id,
            actor=cashier_user,
            target_state="CLINICAL_REVIEW",
        )


def test_knowledge_unavailable_cannot_be_approved(clinical_setup, clinical_user):
    prescription, _ = _prescription(clinical_setup)
    PrescriptionWorkflowService.transition(
        prescription_id=prescription.id, tenant_id=clinical_setup["tenant"].id,
        actor=clinical_user, target_state="CLINICAL_REVIEW"
    )
    evaluation = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=clinical_user)
    with pytest.raises(PrescriptionWorkflowError, match="unavailable"):
        PrescriptionWorkflowService.transition(
            prescription_id=prescription.id, tenant_id=clinical_setup["tenant"].id,
            actor=clinical_user, target_state="APPROVED", clinical_evaluation_id=evaluation.id
        )


def _approve_and_pay(setup, user):
    _release(setup)
    prescription, item = _prescription(setup)
    PrescriptionWorkflowService.transition(
        prescription_id=prescription.id, tenant_id=setup["tenant"].id, actor=user, target_state="CLINICAL_REVIEW"
    )
    evaluation = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=user)
    for state, kwargs in (
        ("APPROVED", {"clinical_evaluation_id": evaluation.id}),
        ("DISPENSING", {}),
        ("READY_FOR_PAYMENT", {}),
        ("PAID", {"payment_reference": "PAY-1001"}),
    ):
        PrescriptionWorkflowService.transition(
            prescription_id=prescription.id, tenant_id=setup["tenant"].id, actor=user, target_state=state, **kwargs
        )
    prescription.refresh_from_db()
    return prescription, item


def test_authorized_state_machine_reaches_paid(clinical_setup, clinical_user):
    prescription, _ = _approve_and_pay(clinical_setup, clinical_user)
    assert prescription.workflow_state == "PAID"
    assert prescription.payment_reference == "PAY-1001"
    assert list(PrescriptionWorkflowEvent.all_objects.filter(prescription=prescription).order_by("created_at").values_list("to_state", flat=True)) == [
        "CLINICAL_REVIEW", "APPROVED", "DISPENSING", "READY_FOR_PAYMENT", "PAID"
    ]


def test_stale_clinical_hash_blocks_progress(clinical_setup, clinical_user):
    _release(clinical_setup)
    prescription, item = _prescription(clinical_setup)
    PrescriptionWorkflowService.transition(
        prescription_id=prescription.id, tenant_id=clinical_setup["tenant"].id,
        actor=clinical_user, target_state="CLINICAL_REVIEW"
    )
    evaluation = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=clinical_user)
    PrescriptionWorkflowService.transition(
        prescription_id=prescription.id, tenant_id=clinical_setup["tenant"].id,
        actor=clinical_user, target_state="APPROVED", clinical_evaluation_id=evaluation.id
    )
    item.quantity = "11"
    item.save()
    with pytest.raises(PrescriptionWorkflowError, match="stale"):
        PrescriptionWorkflowService.transition(
            prescription_id=prescription.id, tenant_id=clinical_setup["tenant"].id,
            actor=clinical_user, target_state="DISPENSING"
        )


def test_dispense_is_idempotent_and_completes_sale(clinical_setup, clinical_user):
    prescription, item = _approve_and_pay(clinical_setup, clinical_user)
    first = DispensingEngine.execute_dispense(
        prescription, clinical_setup["location"],
        [{"prescription_item_id": str(item.id), "quantity": "2"}],
        clinical_user, idempotency_key="DISPENSE-1"
    )
    second = DispensingEngine.execute_dispense(
        prescription, clinical_setup["location"],
        [{"prescription_item_id": str(item.id), "quantity": "2"}],
        clinical_user, idempotency_key="DISPENSE-1"
    )
    assert first.id == second.id
    assert PrescriptionDispense.all_objects.filter(tenant=clinical_setup["tenant"]).count() == 1
    prescription.refresh_from_db()
    assert prescription.workflow_state == "DISPENSED"


def test_dispense_rejects_cross_tenant_location(clinical_setup, clinical_user, tenant_b):
    prescription, item = _approve_and_pay(clinical_setup, clinical_user)
    from apps.organizations.models import Location, Organization

    org_b = Organization.all_objects.create(tenant=tenant_b, name="B", code="B")
    location_b = Location.all_objects.create(tenant=tenant_b, organization=org_b, name="B", code="B")
    with pytest.raises(ValueError, match="outside"):
        DispensingEngine.execute_dispense(
            prescription, location_b,
            [{"prescription_item_id": str(item.id), "quantity": "1"}],
            clinical_user, idempotency_key="DISPENSE-B"
        )
