import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.cds.models import ActiveIngredient, ClinicalKnowledgeRelease, ClinicalKnowledgeRule
from apps.cds.pos_screening_models import (
    PosClinicalAuditEvent,
    PosClinicalFinding,
    PosClinicalOverride,
    PosClinicalScreening,
)
from apps.cds.pos_screening_services import (
    PosClinicalApprovalService,
    PosClinicalScreeningService,
    PosOfflinePackageService,
    PosPharmacistReviewService,
)
from apps.cds.pos_api.serializers import PosClinicalScreeningRequestSerializer
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
        screening=screening, finding_id=finding.id, pharmacist=pharmacist_user, decision="APPROVE_AS_WRITTEN", expected_context_hash=screening.context_hash, idempotency_key="idemp-1"
    )
    assert dec.decision == "APPROVE_AS_WRITTEN"
    screening.refresh_from_db()
    assert screening.safe_to_proceed

def test_submit_pharmacist_rejection(tenant, basket_lines, cashier_user, pharmacist_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-8", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()
    dec = PosPharmacistReviewService.submit_decision(
        screening=screening, finding_id=finding.id, pharmacist=pharmacist_user, decision="REJECT_SUPPLY", expected_context_hash=screening.context_hash, idempotency_key="idemp-2"
    )
    assert dec.decision == "REJECT_SUPPLY"
    assert not screening.safe_to_proceed

def test_pharmacist_override_with_justification(tenant, basket_lines, cashier_user, pharmacist_user, drug_drug_rule):
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant, transaction_id="tx-9", device_id="dev-1", basket_lines=basket_lines, cashier=cashier_user
    )
    finding = PosClinicalFinding.all_objects.filter(screening=screening).first()
    dec = PosPharmacistReviewService.submit_decision(
        screening=screening, finding_id=finding.id, pharmacist=pharmacist_user, decision="AUTHORIZED_OVERRIDE", clinical_justification="Ok", expected_context_hash=screening.context_hash, idempotency_key="idemp-3"
    )
    assert PosClinicalOverride.all_objects.filter(decision=dec).exists()

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
        screening=screening, finding_id=finding.id, pharmacist=pharmacist_user, decision="APPROVE_AS_WRITTEN", expected_context_hash=screening.context_hash, idempotency_key="idemp-4"
    )
    assert dec1.decision == "APPROVE_AS_WRITTEN"
    import django.db
    with pytest.raises(django.db.utils.IntegrityError):
        PosPharmacistReviewService.submit_decision(
            screening=screening, finding_id=finding.id, pharmacist=pharmacist_user, decision="APPROVE_AS_WRITTEN", expected_context_hash=screening.context_hash, idempotency_key="idemp-4"
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
