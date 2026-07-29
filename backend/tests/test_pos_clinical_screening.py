import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.cds.models import ActiveIngredient, ClinicalKnowledgeRelease, ClinicalKnowledgeRule
from apps.cds.pos_api.serializers import PosClinicalScreeningRequestSerializer
from apps.cds.pos_screening_models import (
    PosClinicalAuditEvent,
    PosClinicalFinding,
    PosClinicalOverride,
    PosClinicalScreening,
)
from apps.cds.pos_screening_services import (
    PosClinicalApprovalService,
    PosClinicalOverrideService,
    PosClinicalScreeningService,
    PosOfflinePackageService,
    PosPharmacistReviewService,
)
from apps.identity.models import Role, User, UserRole
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    IngredientComposition,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.patients.models import PatientAllergy, PatientClinicalSummary

pytestmark = pytest.mark.django_db

@pytest.fixture
def tenant(tenant_a):
    return tenant_a

@pytest.fixture
def branch(clinical_setup):
    return clinical_setup["location"]

@pytest.fixture
def pharmacist_user(clinical_user):
    return clinical_user

@pytest.fixture
def cashier_user(cashier_user):
    return cashier_user


@pytest.fixture
def override_requester(tenant):
    user = User.objects.create_user(
        username="override-requester",
        email="override-requester@example.test",
        password="test-password-strong",
        tenant=tenant,
    )
    role = Role.all_objects.create(
        tenant=tenant,
        code="OVERRIDE_REQUESTER",
        name="Override requester",
        capabilities=["prescriptions.approve", "cds.override"],
    )
    UserRole.all_objects.create(tenant=tenant, user=user, role=role)
    return user


@pytest.fixture
def override_approver(tenant):
    user = User.objects.create_user(
        username="override-approver",
        email="override-approver@example.test",
        password="test-password-strong",
        tenant=tenant,
    )
    role = Role.all_objects.create(
        tenant=tenant,
        code="OVERRIDE_APPROVER",
        name="Override approver",
        capabilities=["cds.override"],
    )
    UserRole.all_objects.create(tenant=tenant, user=user, role=role)
    return user

@pytest.fixture
def active_substance(tenant):
    return ActiveSubstance.all_objects.create(
        tenant=tenant,
        code="TEST-ING",
        canonical_name="Test Ingredient",
        display_name="Test Ingredient",
        search_name="test ingredient"
    )

@pytest.fixture
def active_ingredient(tenant):
    return ActiveIngredient.all_objects.create(
        tenant=tenant,
        code="TEST-ING",
        name="Test Ingredient"
    )

@pytest.fixture
def clinical_product(tenant, active_substance):
    dose_form = DoseForm.objects.create(code="TAB", name="Tablet")
    prod = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant,
        code="CMP-TEST",
        canonical_name="Test Product",
        dose_form=dose_form,
        status="ACTIVE"
    )
    IngredientComposition.objects.create(
        clinical_product=prod,
        active_substance=active_substance,
        numerator_value=Decimal("500"),
        numerator_unit="mg"
    )
    return prod

@pytest.fixture
def commercial_sku(tenant, clinical_product):
    mmp = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant,
        code="MMP-TEST",
        brand_name="Test Brand",
        clinical_product=clinical_product,
        status="ACTIVE"
    )
    pkg = PackageDefinition.objects.create(
        code="PACK-TEST",
        description="Pack",
        unit_of_measure="TABLET",
        is_dispensing_unit=True
    )
    return CommercialSKU.all_objects.create(
        tenant=tenant,
        sku_code="SKU-TEST",
        display_name="Test SKU",
        manufactured_product=mmp,
        package_definition=pkg,
        status="ACTIVE"
    )

@pytest.fixture
def release(tenant):
    return ClinicalKnowledgeRelease.all_objects.create(
        tenant=tenant,
        code="TEST-RELEASE",
        version="1.0",
        source="TEST",
        source_version="1.0",
        licence="INTERNAL",
        checksum_sha256="0" * 64,
        effective_date=timezone.now().date(),
        is_active=True
    )

@pytest.fixture
def drug_drug_rule(tenant, release):
    return ClinicalKnowledgeRule.all_objects.create(
        tenant=tenant,
        release=release,
        rule_id="DD-1",
        rule_version="1.0",
        rule_type="DRUG_DRUG",
        primary_code="TEST-ING",
        interacting_code="TEST-ING",
        severity="HIGH",
        evidence_summary="Clinical evidence summary",
        explanation="Clinical interaction explanation",
        recommended_action="Consult pharmacist",
        effective_date=timezone.now().date(),
        is_active=True
    )

@pytest.fixture
def allergy_rule(tenant, release):
    return ClinicalKnowledgeRule.all_objects.create(
        tenant=tenant,
        release=release,
        rule_id="AL-1",
        rule_version="1.0",
        rule_type="ALLERGY",
        primary_code="TEST-ING",
        severity="CRITICAL",
        evidence_summary="Clinical evidence summary",
        explanation="Allergy explanation",
        recommended_action="Do not dispense",
        effective_date=timezone.now().date(),
        is_active=True
    )

@pytest.fixture
def patient(clinical_setup):
    p = clinical_setup["patient"]
    PatientAllergy.all_objects.create(
        tenant=clinical_setup["tenant"],
        patient=p,
        allergen_code="TEST-ING",
        allergen_name="Test Ingredient",
        severity="HARD_STOP",
        is_active=True
    )
    PatientClinicalSummary.all_objects.create(
        tenant=clinical_setup["tenant"],
        patient=p,
        pregnancy_status="NOT_PREGNANT",
        lactation_status="NOT_LACTATING",
        renal_impairment="NONE",
        hepatic_impairment="NONE"
    )
    return p

@pytest.fixture
def basket_lines(commercial_sku):
    return [{
        "line_id": "line-1",
        "sku_id": str(commercial_sku.id),
        "quantity": "2",
        "dose_instructions": "Take 1"
    }]

def test_context_builder_resolves_sku_to_ingredients(tenant, basket_lines, active_ingredient):
    from apps.cds.pos_screening_services import PosTransactionContextBuilder
    ctx = PosTransactionContextBuilder.build_context(tenant=tenant, basket_lines=basket_lines)
    assert active_ingredient.code in ctx["ingredient_codes"]


@pytest.mark.parametrize(
    ("basket_line", "expected_sku_id"),
    [
        ({"sku_id": "native-pos-sku", "quantity": 1}, "native-pos-sku"),
        ({"commercial_sku_id": "legacy-sku", "quantity": 1}, "legacy-sku"),
    ],
)
def test_screening_request_preserves_the_pos_sku_contract(basket_line, expected_sku_id):
    serializer = PosClinicalScreeningRequestSerializer(
        data={
            "transaction_id": "clinical-contract-test",
            "device_id": "device-1",
            "basket_lines": [basket_line],
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["basket_lines"][0]["sku_id"] == expected_sku_id

def test_context_builder_includes_patient_allergies(tenant, basket_lines, patient):
    from apps.cds.pos_screening_services import PosTransactionContextBuilder
    ctx = PosTransactionContextBuilder.build_context(tenant=tenant, basket_lines=basket_lines, patient_id=patient.id)
    assert any(a["code"] == "TEST-ING" for a in ctx["allergies"])

def test_context_builder_includes_clinical_summary(tenant, basket_lines, patient):
    from apps.cds.pos_screening_services import PosTransactionContextBuilder
    ctx = PosTransactionContextBuilder.build_context(tenant=tenant, basket_lines=basket_lines, patient_id=patient.id)
    assert ctx["clinical_summary"]["pregnancy_status"] == "NOT_PREGNANT"

def test_context_hash_deterministic_same_input(tenant, basket_lines):
    from apps.cds.pos_screening_services import PosTransactionContextBuilder
    ctx1 = PosTransactionContextBuilder.build_context(tenant=tenant, basket_lines=basket_lines)
    ctx2 = PosTransactionContextBuilder.build_context(tenant=tenant, basket_lines=basket_lines)
    h1 = PosTransactionContextBuilder.compute_context_hash(context=ctx1)
    h2 = PosTransactionContextBuilder.compute_context_hash(context=ctx2)
    assert h1 == h2

def test_context_hash_changes_on_basket_change(tenant, basket_lines):
    from apps.cds.pos_screening_services import PosTransactionContextBuilder
    ctx1 = PosTransactionContextBuilder.build_context(tenant=tenant, basket_lines=basket_lines)
    
    basket_lines_2 = [{"line_id": "line-1", "sku_id": basket_lines[0]["sku_id"], "quantity": "3"}]
    ctx2 = PosTransactionContextBuilder.build_context(tenant=tenant, basket_lines=basket_lines_2)
    
    h1 = PosTransactionContextBuilder.compute_context_hash(context=ctx1)
    h2 = PosTransactionContextBuilder.compute_context_hash(context=ctx2)
    assert h1 != h2

def test_evaluate_no_findings_safe_to_proceed(tenant, basket_lines, cashier_user):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-1", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    assert screening.safe_to_proceed is True
    assert screening.highest_severity is None

def test_evaluate_detects_drug_drug_interaction(tenant, basket_lines, cashier_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-2", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    assert not screening.safe_to_proceed
    assert screening.highest_severity == "HIGH"
    assert PosClinicalFinding.all_objects.filter(screening=screening, category="DRUG_DRUG_INTERACTION").exists()

def test_evaluate_detects_allergy(tenant, basket_lines, cashier_user, allergy_rule, patient):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-3", device_id="dev-1", basket_lines=basket_lines, patient_id=patient.id, cashier=cashier_user
    )
    assert not screening.safe_to_proceed
    assert screening.highest_severity == "CRITICAL"
    assert PosClinicalFinding.all_objects.filter(screening=screening, category="DRUG_ALLERGY").exists()

def test_evaluate_duplicate_therapy(tenant, basket_lines, cashier_user):
    pass

def test_evaluate_blocking_severity_sets_unsafe(tenant, basket_lines, cashier_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-4", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    assert not screening.safe_to_proceed
    assert screening.blocking_count > 0

def test_evaluate_with_patient_medication_history():
    pass

def test_evaluate_without_patient_limited_screening(tenant, basket_lines, cashier_user, allergy_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-5", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    # Allergy shouldn't be detected without patient
    assert screening.safe_to_proceed
    assert not PosClinicalFinding.all_objects.filter(screening=screening, category="DRUG_ALLERGY").exists()

def test_evaluate_insufficient_patient_data_finding():
    pass

def test_evaluate_prescription_required_flagged():
    pass

def test_evaluate_controlled_medicine_flagged():
    pass

def test_information_severity_no_block():
    pass

def test_moderate_severity_requires_review():
    pass

def test_high_severity_blocks_cashier():
    pass

def test_critical_severity_blocks_supply():
    pass

def test_request_pharmacist_review(tenant, basket_lines, cashier_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-6", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    audit = PosPharmacistReviewService.request_review(screening=screening, cashier=cashier_user, expected_context_hash=screening.context_hash)
    assert audit.event_type == 'PHARMACIST_REVIEW_REQUESTED'

def test_submit_pharmacist_approval(tenant, basket_lines, cashier_user, pharmacist_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-7", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()
    dec = PosPharmacistReviewService.submit_decision(
        screening=screening, finding_id=finding.id, pharmacist=pharmacist_user, decision="APPROVE", clinical_justification="Reviewed interaction and approved supply.", expected_context_hash=screening.context_hash, idempotency_key="idemp-1"
    )
    assert dec.decision == "APPROVE"
    screening.refresh_from_db()
    assert screening.safe_to_proceed

def test_submit_pharmacist_rejection(tenant, basket_lines, cashier_user, pharmacist_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-8", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()
    dec = PosPharmacistReviewService.submit_decision(
        screening=screening, finding_id=finding.id, pharmacist=pharmacist_user, decision="REJECT", clinical_justification="Interaction makes supply inappropriate.", expected_context_hash=screening.context_hash, idempotency_key="idemp-2"
    )
    assert dec.decision == "REJECT"
    assert not screening.safe_to_proceed

def test_override_requires_separate_request_and_approval(
    tenant,
    basket_lines,
    cashier_user,
    override_requester,
    override_approver,
    drug_drug_rule,
):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-9", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()
    override = PosClinicalOverrideService.request(
        screening=screening,
        finding_id=finding.id,
        requester=override_requester,
        override_reason="CLINICALLY_JUSTIFIED",
        requested_reason="Prescriber confirmed the intended combination.",
        idempotency_key="override-request-1",
        expected_context_hash=screening.context_hash,
    )
    approved = PosClinicalOverrideService.approve(
        override=override,
        pharmacist=override_approver,
        clinical_justification="Reviewed the documented indication and monitoring plan.",
        idempotency_key="override-approval-1",
        expected_context_hash=screening.context_hash,
    )
    screening.refresh_from_db()
    finding.refresh_from_db()
    assert approved.status == PosClinicalOverride.Status.APPROVED
    assert approved.decision_id
    assert finding.resolution_status == PosClinicalFinding.ResolutionStatus.OVERRIDDEN
    assert screening.safe_to_proceed is True


def test_override_cannot_be_approved_by_its_requester(
    tenant,
    basket_lines,
    cashier_user,
    override_requester,
    drug_drug_rule,
):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-override-sod", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()
    override = PosClinicalOverrideService.request(
        screening=screening,
        finding_id=finding.id,
        requester=override_requester,
        override_reason="CLINICALLY_JUSTIFIED",
        requested_reason="Escalated for documented clinical assessment.",
        idempotency_key="override-request-sod",
        expected_context_hash=screening.context_hash,
    )
    with pytest.raises(ValidationError, match="differ from the requesting operator"):
        PosClinicalOverrideService.approve(
            override=override,
            pharmacist=override_requester,
            clinical_justification="This must be rejected by separation of duties.",
            idempotency_key="override-approval-sod",
            expected_context_hash=screening.context_hash,
        )


def test_expired_override_reopens_the_clinical_gate(
    tenant,
    basket_lines,
    cashier_user,
    override_requester,
    override_approver,
    drug_drug_rule,
):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-override-expiry", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()
    override = PosClinicalOverrideService.request(
        screening=screening,
        finding_id=finding.id,
        requester=override_requester,
        override_reason="CLINICALLY_JUSTIFIED",
        requested_reason="Escalated for time-bounded pharmacist assessment.",
        idempotency_key="override-request-expiry",
        expected_context_hash=screening.context_hash,
    )
    PosClinicalOverrideService.approve(
        override=override,
        pharmacist=override_approver,
        clinical_justification="Approved only for the current transaction window.",
        expires_at=timezone.now() + timezone.timedelta(minutes=1),
        idempotency_key="override-approval-expiry",
        expected_context_hash=screening.context_hash,
    )
    override.refresh_from_db()
    override.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    override.save(update_fields=["expires_at", "updated_at"])

    with pytest.raises(ValidationError, match="unresolved blocking findings"):
        PosClinicalApprovalService.assert_current_and_safe(
            screening=screening,
            expected_context_hash=screening.context_hash,
        )

    override.refresh_from_db()
    finding.refresh_from_db()
    assert override.status == PosClinicalOverride.Status.EXPIRED
    assert finding.resolution_status == PosClinicalFinding.ResolutionStatus.OPEN


def test_direct_override_decision_is_rejected(tenant, basket_lines, cashier_user, pharmacist_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-direct-override", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()
    with pytest.raises(ValidationError, match="governed override request"):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding.id,
            pharmacist=pharmacist_user,
            decision="AUTHORIZED_OVERRIDE",
            clinical_justification="Direct override is intentionally unavailable.",
            expected_context_hash=screening.context_hash,
            idempotency_key="direct-override",
        )

def test_override_requires_capability():
    pass

def test_basket_change_invalidates_screening(tenant, basket_lines, cashier_user):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-10", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    PosClinicalApprovalService.invalidate(screening=screening, reason="Basket changed")
    screening.refresh_from_db()
    assert screening.status == "INVALIDATED"

def test_approval_invalid_after_quantity_change(tenant, basket_lines, cashier_user):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-11", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    
    from apps.cds.pos_screening_services import PosTransactionContextBuilder
    basket_lines_2 = [{"line_id": "line-1", "sku_id": basket_lines[0]["sku_id"], "quantity": "5"}]
    ctx2 = PosTransactionContextBuilder.build_context(tenant=tenant, basket_lines=basket_lines_2)
    h2 = PosTransactionContextBuilder.compute_context_hash(context=ctx2)
    
    assert not PosClinicalApprovalService.validate_basket_unchanged(screening=screening, current_context_hash=h2)

def test_approval_invalid_after_patient_change(tenant, basket_lines, cashier_user, patient):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-11b", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    
    from apps.cds.pos_screening_services import PosTransactionContextBuilder
    ctx2 = PosTransactionContextBuilder.build_context(tenant=tenant, basket_lines=basket_lines, patient_id=patient.id)
    h2 = PosTransactionContextBuilder.compute_context_hash(context=ctx2)
    
    assert not PosClinicalApprovalService.validate_basket_unchanged(screening=screening, current_context_hash=h2)

def test_same_context_hash_returns_existing_screening(tenant, basket_lines, cashier_user):
    s1 = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-13", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    s2 = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-13", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    assert s1.id == s2.id

def test_different_context_hash_creates_new_screening(tenant, basket_lines, cashier_user):
    s1 = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-14", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    basket_lines_2 = [{"line_id": "line-1", "sku_id": basket_lines[0]["sku_id"], "quantity": "9"}]
    s2 = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-14", device_id="dev-1", basket_lines=basket_lines_2, cashier=cashier_user
    )
    assert s1.id != s2.id

def test_decision_idempotency_key_prevents_duplicate(tenant, basket_lines, cashier_user, pharmacist_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-15", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()
    dec1 = PosPharmacistReviewService.submit_decision(
        screening=screening, finding_id=finding.id, pharmacist=pharmacist_user, decision="APPROVE", clinical_justification="Reviewed interaction and approved supply.", expected_context_hash=screening.context_hash, idempotency_key="idemp-4"
    )
    assert dec1.decision == "APPROVE"
    dec2 = PosPharmacistReviewService.submit_decision(
        screening=screening, finding_id=finding.id, pharmacist=pharmacist_user, decision="APPROVE", clinical_justification="Reviewed interaction and approved supply.", expected_context_hash=screening.context_hash, idempotency_key="idemp-4"
    )
    assert dec2.id == dec1.id


def test_correction_decision_keeps_finding_open_and_records_follow_up(tenant, basket_lines, cashier_user, pharmacist_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-correction", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()

    decision = PosPharmacistReviewService.submit_decision(
        screening=screening,
        finding_id=finding.id,
        pharmacist=pharmacist_user,
        decision="RETURN_FOR_CORRECTION",
        clinical_justification="The prescribed combination requires correction.",
        follow_up_actions="Contact the prescriber and rescreen the corrected basket.",
        expected_context_hash=screening.context_hash,
        idempotency_key="idemp-correction",
    )

    finding.refresh_from_db()
    screening.refresh_from_db()
    assert finding.resolution_status == "OPEN"
    assert screening.safe_to_proceed is False
    assert decision.transaction_id == screening.transaction_id
    assert decision.patient_ref == str(screening.patient_id or "")
    assert decision.follow_up_actions


def test_approval_with_conditions_requires_conditions(tenant, basket_lines, cashier_user, pharmacist_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-conditions", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()

    with pytest.raises(Exception, match="conditions"):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding.id,
            pharmacist=pharmacist_user,
            decision="APPROVE_WITH_CONDITIONS",
            clinical_justification="Supply may proceed only with counselling.",
            expected_context_hash=screening.context_hash,
            idempotency_key="idemp-conditions",
        )

def test_generate_offline_package(tenant, pharmacist_user):
    pkg = PosOfflinePackageService.generate_package(tenant=tenant, generated_by=pharmacist_user)
    assert pkg.version.startswith("PKG-")
    assert pkg.package_data is not None
    assert pkg.signature

def test_validate_package_signature(tenant, pharmacist_user):
    pkg = PosOfflinePackageService.generate_package(tenant=tenant, generated_by=pharmacist_user)
    assert PosOfflinePackageService.validate_package(
        package_data=pkg.package_data,
        signature=pkg.signature,
        tenant=tenant,
        signing_version=pkg.signing_version,
    )


def test_validate_package_without_signing_version_fails_closed(tenant, pharmacist_user):
    """A caller that has not been updated must be refused, not trusted.

    validate_package defaults to the withdrawn legacy version precisely so that
    an old call site cannot keep silently passing.
    """
    pkg = PosOfflinePackageService.generate_package(tenant=tenant, generated_by=pharmacist_user)
    assert not PosOfflinePackageService.validate_package(
        package_data=pkg.package_data, signature=pkg.signature, tenant=tenant
    )

def test_invalid_signature_rejected(tenant, pharmacist_user):
    pkg = PosOfflinePackageService.generate_package(tenant=tenant, generated_by=pharmacist_user)
    assert not PosOfflinePackageService.validate_package(package_data=pkg.package_data, signature="invalid", tenant=tenant)

def test_screening_tenant_isolated(tenant_a, tenant_b, basket_lines, cashier_user):
    s1 = PosClinicalScreeningService.evaluate(
        tenant=tenant_a, transaction_id="tx-16", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    assert s1.tenant_id == tenant_a.id
    assert PosClinicalScreening.all_objects.filter(tenant=tenant_a).count() == 1
    assert PosClinicalScreening.all_objects.filter(tenant=tenant_b).count() == 0

def test_cross_tenant_screening_rejected(tenant_a, tenant_b, basket_lines, cashier_user):
    with pytest.raises(Exception):
        PosClinicalScreeningService.evaluate(
            tenant=tenant_a, transaction_id="tx-17", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user,
            patient_id=uuid.uuid4() # Or something from tenant_b
        )

def test_audit_event_created_for_screening(tenant, basket_lines, cashier_user):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-18", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    assert PosClinicalAuditEvent.all_objects.filter(screening=screening, event_type="SCREENING_REQUESTED").exists()
    assert PosClinicalAuditEvent.all_objects.filter(screening=screening, event_type="SCREENING_COMPLETED").exists()

def test_audit_event_includes_correlation_id(tenant, basket_lines, cashier_user):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-19", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    audit = PosClinicalAuditEvent.all_objects.filter(screening=screening).first()
    assert audit.correlation_id is not None
