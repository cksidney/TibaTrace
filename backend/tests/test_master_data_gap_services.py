"""The five authoritative services Stage 2A needed.

Each closes a gap where the only existing write path was a seed command going
straight to the ORM. The tests below concentrate on the refusals, because a
service that creates rows but declines nothing is the ORM with extra steps.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.identity.models import User
from apps.insurance.models import CoverageBenefit, InsuranceCoverage, Insurer
from apps.insurance.services.authoring import (
    InsuranceBenefitService,
    InsuranceMembershipService,
)
from apps.insurance.services.onboarding import InsurerOnboardingService
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    Manufacturer,
    PackageDefinition,
)
from apps.medicines.provisioning import (
    BranchAssortmentProvisioningService,
    CatalogueFilters,
    CatalogueFitnessError,
    CatalogueFitnessService,
    CatalogueSelectionService,
    TenantCatalogueProvisioningService,
)
from apps.organizations.services import (
    OrganizationProvisioningService,
    SiteProvisioningService,
)
from apps.patients.models import Patient
from apps.pricing.authoring import PriceBookService
from apps.pricing.models import PriceBook, PriceBookEntry, PriceBookVersion
from apps.procurement.models import SupplierProductAgreement, SupplierQualification
from apps.procurement.services.supplier_agreement_service import (
    SupplierProductAgreementService,
)
from apps.procurement.services.supplier_governance_service import SupplierGovernanceService
from apps.procurement.services.supplier_qualification_service import (
    SupplierQualificationService,
)
from apps.tenancy.models import Tenant

TODAY = date(2026, 8, 3)
Status = SupplierQualification.QualificationVerificationStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Gap Chemists", slug="gapchem")


@pytest.fixture
def submitter(db, tenant):
    return User.objects.create(username="gap.submitter", tenant=tenant, is_superuser=True)


@pytest.fixture
def reviewer(db, tenant):
    return User.objects.create(username="gap.reviewer", tenant=tenant, is_superuser=True)


@pytest.fixture
def branch(db, tenant):
    org = OrganizationProvisioningService.provision_organization(
        tenant=tenant, code="GAP-ORG", name="Gap Chemists Ltd"
    )
    return SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="GAP-CBD", name="CBD"
    )


@pytest.fixture
def catalogue(db):
    """A minimal global catalogue: one fit product, one recalled path."""
    form = DoseForm.objects.create(code="TAB", name="Tablet")
    manufacturer = Manufacturer.objects.create(
        code="GBL-MFR", is_global=True, legal_name="Global Pharma", country="IN"
    )
    clinical = ClinicalMedicinalProduct.objects.create(
        is_global=True, code="CMP-FIT", canonical_name="Paracetamol 500mg",
        dose_form=form, status=ClinicalMedicinalProduct.STATUS_ACTIVE,
        controlled_classification="NONE",
    )
    suspended_clinical = ClinicalMedicinalProduct.objects.create(
        is_global=True, code="CMP-SUS", canonical_name="Suspended Product",
        dose_form=form, status=ClinicalMedicinalProduct.STATUS_SUSPENDED,
    )
    controlled_clinical = ClinicalMedicinalProduct.objects.create(
        is_global=True, code="CMP-CTRL", canonical_name="Morphine 10mg",
        dose_form=form, status=ClinicalMedicinalProduct.STATUS_ACTIVE,
        controlled_classification="SCHEDULE_II",
    )
    fit = ManufacturedMedicinalProduct.objects.create(
        is_global=True, code="MP-FIT", brand_name="Panadol", clinical_product=clinical,
        manufacturer=manufacturer, status=ManufacturedMedicinalProduct.STATUS_ACTIVE,
        market_authorisation_number="MA-001",
    )
    withdrawn = ManufacturedMedicinalProduct.objects.create(
        is_global=True, code="MP-WDN", brand_name="Withdrawn Brand",
        clinical_product=clinical, manufacturer=manufacturer,
        status=ManufacturedMedicinalProduct.STATUS_WITHDRAWN,
    )
    on_suspended = ManufacturedMedicinalProduct.objects.create(
        is_global=True, code="MP-SUS", brand_name="On Suspended Clinical",
        clinical_product=suspended_clinical, manufacturer=manufacturer,
        status=ManufacturedMedicinalProduct.STATUS_ACTIVE,
    )
    controlled = ManufacturedMedicinalProduct.objects.create(
        is_global=True, code="MP-CTRL", brand_name="Morphine Brand",
        clinical_product=controlled_clinical, manufacturer=manufacturer,
        status=ManufacturedMedicinalProduct.STATUS_ACTIVE,
    )
    package = PackageDefinition.objects.create(
        code="PKG-30", description="Box of 30", unit_of_measure="tablet", is_active=True
    )
    return {
        "fit": fit, "withdrawn": withdrawn, "on_suspended": on_suspended,
        "controlled": controlled, "package": package, "manufacturer": manufacturer,
    }


@pytest.fixture
def sku(db, tenant, catalogue):
    return TenantCatalogueProvisioningService.provision_sku(
        tenant=tenant, manufactured_product=catalogue["fit"],
        package_definition=catalogue["package"], sku_code="GAP-SKU-001",
    )


# ---------------------------------------------------------------------------
# 1. Catalogue and assortment
# ---------------------------------------------------------------------------


def test_listing_a_withdrawn_product_is_refused(db, tenant, catalogue):
    """A regulator-withdrawn product must never enter a tenant catalogue."""
    with pytest.raises(CatalogueFitnessError, match="manufactured product"):
        TenantCatalogueProvisioningService.provision_sku(
            tenant=tenant, manufactured_product=catalogue["withdrawn"],
            package_definition=catalogue["package"], sku_code="GAP-BAD-1",
        )


def test_listing_on_a_suspended_clinical_product_is_refused(db, tenant, catalogue):
    with pytest.raises(CatalogueFitnessError, match="clinical product"):
        TenantCatalogueProvisioningService.provision_sku(
            tenant=tenant, manufactured_product=catalogue["on_suspended"],
            package_definition=catalogue["package"], sku_code="GAP-BAD-2",
        )


def test_listing_reuses_the_global_record(db, tenant, catalogue, sku):
    """The SKU is tenant-owned; the product behind it stays global."""
    assert sku.tenant_id == tenant.id
    assert sku.manufactured_product.is_global is True
    assert sku.manufactured_product.tenant_id is None


def test_sku_provisioning_is_idempotent(db, tenant, catalogue):
    first = TenantCatalogueProvisioningService.provision_sku(
        tenant=tenant, manufactured_product=catalogue["fit"],
        package_definition=catalogue["package"], sku_code="GAP-IDEM",
    )
    second = TenantCatalogueProvisioningService.provision_sku(
        tenant=tenant, manufactured_product=catalogue["fit"],
        package_definition=catalogue["package"], sku_code="GAP-IDEM",
    )
    assert first.pk == second.pk


def test_assorting_a_recalled_sku_is_refused(db, tenant, branch, sku):
    """The failure the old enable_sku_for_branch allowed through silently."""
    sku.status = CommercialSKU.STATUS_RECALLED
    sku.save(update_fields=["status"])
    with pytest.raises(CatalogueFitnessError, match="recalled"):
        BranchAssortmentProvisioningService.provision(
            tenant=tenant, branch=branch, sku=sku
        )


def test_assortment_is_idempotent_and_creates_no_stock(db, tenant, branch, sku):
    from apps.inventory.models import InventoryBatch, InventoryLedgerEntry

    first = BranchAssortmentProvisioningService.provision(
        tenant=tenant, branch=branch, sku=sku
    )
    second = BranchAssortmentProvisioningService.provision(
        tenant=tenant, branch=branch, sku=sku
    )
    assert first.pk == second.pk
    assert InventoryBatch.all_objects.filter(tenant=tenant).count() == 0
    assert InventoryLedgerEntry.all_objects.filter(tenant=tenant).count() == 0


def test_unavailable_assortment_cannot_also_be_stocked(db, tenant, branch, sku):
    """A line nobody can dispense must not appear as stocked."""
    assortment = BranchAssortmentProvisioningService.provision(
        tenant=tenant, branch=branch, sku=sku,
        formulary_status=BranchAssortmentProvisioningService.TEMPORARILY_UNAVAILABLE,
        is_stocked=True,
    )
    assert assortment.is_stocked is False
    assert assortment.is_dispensable is False


def test_withdrawing_a_sku_clears_every_branch_assortment(db, tenant, branch, sku, submitter):
    """Otherwise a centrally recalled product stays on a branch shelf report."""
    BranchAssortmentProvisioningService.provision(tenant=tenant, branch=branch, sku=sku)
    TenantCatalogueProvisioningService.withdraw_sku(
        sku=sku, actor=submitter, reason="recalled",
        status=CommercialSKU.STATUS_RECALLED,
    )
    from apps.medicines.models import BranchAssortment

    assortment = BranchAssortment.all_objects.get(tenant=tenant, sku=sku)
    assert assortment.is_sellable is False
    assert assortment.is_dispensable is False


def test_bulk_assortment_reports_unfit_lines_instead_of_stocking_them(db, tenant, branch, catalogue, sku):
    unfit = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="GAP-UNFIT", display_name="Unfit",
        manufactured_product=catalogue["fit"], package_definition=catalogue["package"],
        status=CommercialSKU.STATUS_DISCONTINUED,
    )
    provisioned, rejected = BranchAssortmentProvisioningService.provision_many(
        tenant=tenant, branch=branch, skus=[sku, unfit], skip_unfit=True,
    )
    assert len(provisioned) == 1
    assert len(rejected) == 1
    assert rejected[0].sku_code == "GAP-UNFIT"


def test_deterministic_selection_is_stable_and_insensitive_to_new_arrivals(db, tenant, catalogue):
    """Adding a product must not change which of the others were selected."""
    for index in range(10):
        TenantCatalogueProvisioningService.provision_sku(
            tenant=tenant, manufactured_product=catalogue["fit"],
            package_definition=catalogue["package"], sku_code=f"GAP-SEL-{index:03d}",
        )
    first = CatalogueSelectionService.select_deterministic(tenant=tenant, count=5, seed=42)
    again = CatalogueSelectionService.select_deterministic(tenant=tenant, count=5, seed=42)
    assert [s.sku_code for s in first] == [s.sku_code for s in again]

    TenantCatalogueProvisioningService.provision_sku(
        tenant=tenant, manufactured_product=catalogue["fit"],
        package_definition=catalogue["package"], sku_code="GAP-SEL-NEW",
    )
    after = CatalogueSelectionService.select_deterministic(tenant=tenant, count=5, seed=42)
    # At most the new arrival displaces one entry; a seeded shuffle would
    # reorder everything.
    assert len(set(s.sku_code for s in first) & set(s.sku_code for s in after)) >= 4


def test_selection_filters_on_controlled_status(db, tenant, catalogue):
    plain = TenantCatalogueProvisioningService.provision_sku(
        tenant=tenant, manufactured_product=catalogue["fit"],
        package_definition=catalogue["package"], sku_code="GAP-PLAIN",
    )
    controlled = TenantCatalogueProvisioningService.provision_sku(
        tenant=tenant, manufactured_product=catalogue["controlled"],
        package_definition=catalogue["package"], sku_code="GAP-CTRL",
    )
    only_controlled = CatalogueSelectionService.eligible_skus(
        tenant=tenant, filters=CatalogueFilters(controlled=True)
    )
    assert [s.pk for s in only_controlled] == [controlled.pk]
    uncontrolled = CatalogueSelectionService.eligible_skus(
        tenant=tenant, filters=CatalogueFilters(controlled=False)
    )
    assert plain.pk in [s.pk for s in uncontrolled]


def test_fitness_is_answerable_without_acting(db, sku):
    assert CatalogueFitnessService.is_assortable(sku) is True
    sku.status = CommercialSKU.STATUS_INACTIVE
    assert CatalogueFitnessService.is_assortable(sku) is False


# ---------------------------------------------------------------------------
# 2. Supplier qualifications
# ---------------------------------------------------------------------------


@pytest.fixture
def supplier(db, tenant, reviewer):
    supplier = SupplierGovernanceService.create_supplier(
        tenant=tenant, supplier_code="GAP-SUP", legal_name="Gap Distributors"
    )
    SupplierGovernanceService.approve_supplier(
        supplier=supplier, approver=reviewer, reason="approved for test"
    )
    supplier.refresh_from_db()
    return supplier


def _register(tenant, supplier, submitter, kind="BUSINESS_REGISTRATION", **kwargs):
    return SupplierQualificationService.register_qualification(
        tenant=tenant, supplier=supplier, qualification_type=kind,
        licence_number=kwargs.pop("licence_number", f"LIC-{kind}"),
        issuing_authority="Test Authority",
        effective_date=kwargs.pop("effective_date", TODAY - timedelta(days=100)),
        expiry_date=kwargs.pop("expiry_date", date.today() + timedelta(days=365)),
        submitted_by=submitter, **kwargs,
    )


def test_a_registered_qualification_starts_pending(db, tenant, supplier, submitter):
    """There is no argument that creates a verified qualification."""
    qualification = _register(tenant, supplier, submitter)
    assert qualification.verification_status == Status.PENDING
    assert qualification.verified_by_id is None
    assert qualification.submitted_by_id == submitter.id


def test_self_verification_is_refused(db, tenant, supplier, submitter):
    """One person must not register a licence and approve their own evidence."""
    qualification = _register(tenant, supplier, submitter)
    with pytest.raises(PermissionDenied, match="Self-verification"):
        SupplierQualificationService.verify_qualification(
            qualification=qualification, verifier=submitter
        )


def test_verification_records_manual_basis_not_a_regulator_lookup(
    db, tenant, supplier, submitter, reviewer
):
    qualification = _register(tenant, supplier, submitter)
    SupplierQualificationService.verify_qualification(
        qualification=qualification, verifier=reviewer
    )
    qualification.refresh_from_db()
    assert qualification.verification_status == Status.VERIFIED
    assert qualification.verification_basis == "MANUAL_INTERNAL_VERIFICATION"


def test_an_already_expired_document_cannot_be_registered(db, tenant, supplier, submitter):
    with pytest.raises(ValidationError, match="expired"):
        _register(
            tenant, supplier, submitter,
            effective_date=date.today() - timedelta(days=800),
            expiry_date=date.today() - timedelta(days=1),
        )


def test_a_second_live_licence_of_the_same_type_is_refused(db, tenant, supplier, submitter):
    """Two live licences make 'which one authorised this?' unanswerable."""
    _register(tenant, supplier, submitter, licence_number="LIC-A")
    with pytest.raises(ValidationError, match="already holds"):
        _register(tenant, supplier, submitter, licence_number="LIC-B")


def test_registering_the_same_licence_twice_is_idempotent(db, tenant, supplier, submitter):
    first = _register(tenant, supplier, submitter, licence_number="LIC-SAME")
    second = _register(tenant, supplier, submitter, licence_number="LIC-SAME")
    assert first.pk == second.pk


def test_a_suspended_supplier_cannot_gain_qualifications(db, tenant, supplier, submitter, reviewer):
    SupplierGovernanceService.suspend_supplier(
        supplier=supplier, approver=reviewer, reason="under investigation"
    )
    supplier.refresh_from_db()
    with pytest.raises(ValidationError, match="cannot receive"):
        _register(tenant, supplier, submitter)


def test_revocation_and_expiry_are_distinct_and_audited(
    db, tenant, supplier, submitter, reviewer
):
    qualification = _register(tenant, supplier, submitter)
    SupplierQualificationService.verify_qualification(
        qualification=qualification, verifier=reviewer
    )
    qualification.refresh_from_db()
    SupplierQualificationService.revoke_qualification(
        qualification=qualification, actor=reviewer, reason="licence withdrawn by authority"
    )
    qualification.refresh_from_db()
    assert qualification.verification_status == Status.REVOKED
    assert "withdrawn" in qualification.decision_reason
    # History remains queryable rather than deleted.
    assert SupplierQualification.all_objects.filter(pk=qualification.pk).exists()


def test_a_current_qualification_cannot_be_expired_early(db, tenant, supplier, submitter, reviewer):
    qualification = _register(tenant, supplier, submitter)
    SupplierQualificationService.verify_qualification(
        qualification=qualification, verifier=reviewer
    )
    qualification.refresh_from_db()
    with pytest.raises(ValidationError, match="current until"):
        SupplierQualificationService.expire_qualification(qualification=qualification)


def test_holds_reports_only_current_verified_qualifications(
    db, tenant, supplier, submitter, reviewer
):
    assert SupplierQualificationService.holds(
        supplier=supplier, qualification_type="COLD_CHAIN_AUTHORIZATION"
    ) is False
    qualification = _register(tenant, supplier, submitter, kind="COLD_CHAIN_AUTHORIZATION")
    assert SupplierQualificationService.holds(
        supplier=supplier, qualification_type="COLD_CHAIN_AUTHORIZATION"
    ) is False, "pending is not held"
    SupplierQualificationService.verify_qualification(
        qualification=qualification, verifier=reviewer
    )
    assert SupplierQualificationService.holds(
        supplier=supplier, qualification_type="COLD_CHAIN_AUTHORIZATION"
    ) is True


# ---------------------------------------------------------------------------
# 3. Supplier product agreements
# ---------------------------------------------------------------------------


def test_a_controlled_line_requires_a_controlled_drug_licence(
    db, tenant, supplier, catalogue, submitter, reviewer
):
    """The regulatory exposure this hardening exists for."""
    controlled_sku = TenantCatalogueProvisioningService.provision_sku(
        tenant=tenant, manufactured_product=catalogue["controlled"],
        package_definition=catalogue["package"], sku_code="GAP-CTRL-SKU",
    )
    with pytest.raises(ValidationError, match="CONTROLLED_DRUG_LICENCE"):
        SupplierProductAgreementService.register_agreement(
            tenant=tenant, supplier=supplier, sku=controlled_sku,
            agreed_unit_price=Decimal("100.00"),
        )

    qualification = _register(
        tenant, supplier, submitter, kind="CONTROLLED_DRUG_LICENCE"
    )
    SupplierQualificationService.verify_qualification(
        qualification=qualification, verifier=reviewer
    )
    agreement = SupplierProductAgreementService.register_agreement(
        tenant=tenant, supplier=supplier, sku=controlled_sku,
        agreed_unit_price=Decimal("100.00"),
    )
    assert agreement.pk is not None


def test_an_unapproved_supplier_cannot_be_contracted_with(db, tenant, sku):
    prospective = SupplierGovernanceService.create_supplier(
        tenant=tenant, supplier_code="GAP-PROSPECT", legal_name="Prospective Ltd"
    )
    with pytest.raises(ValidationError, match="cannot be contracted"):
        SupplierProductAgreementService.register_agreement(
            tenant=tenant, supplier=prospective, sku=sku,
            agreed_unit_price=Decimal("10.00"),
        )


def test_an_inactive_sku_cannot_be_contracted_for(db, tenant, supplier, sku):
    sku.status = CommercialSKU.STATUS_DISCONTINUED
    sku.save(update_fields=["status"])
    with pytest.raises(ValidationError, match="DISCONTINUED"):
        SupplierProductAgreementService.register_agreement(
            tenant=tenant, supplier=supplier, sku=sku, agreed_unit_price=Decimal("10.00"),
        )


def test_agreed_price_is_quantized_not_truncated(db, tenant, supplier, sku):
    agreement = SupplierProductAgreementService.register_agreement(
        tenant=tenant, supplier=supplier, sku=sku, agreed_unit_price="10.999",
    )
    assert agreement.agreed_unit_price == Decimal("11.00")


def test_negative_and_zero_prices_are_refused(db, tenant, supplier, sku):
    for bad in ("-1.00", "0.00"):
        with pytest.raises(ValidationError):
            SupplierProductAgreementService.register_agreement(
                tenant=tenant, supplier=supplier, sku=sku, agreed_unit_price=bad,
            )


def test_only_one_preferred_supplier_per_sku(db, tenant, supplier, sku, reviewer):
    other = SupplierGovernanceService.create_supplier(
        tenant=tenant, supplier_code="GAP-SUP-2", legal_name="Second Distributors"
    )
    SupplierGovernanceService.approve_supplier(
        supplier=other, approver=reviewer, reason="approved"
    )
    other.refresh_from_db()

    SupplierProductAgreementService.register_agreement(
        tenant=tenant, supplier=supplier, sku=sku,
        agreed_unit_price=Decimal("10.00"), is_preferred=True,
    )
    SupplierProductAgreementService.register_agreement(
        tenant=tenant, supplier=other, sku=sku,
        agreed_unit_price=Decimal("9.00"), is_preferred=True,
    )
    preferred = SupplierProductAgreement.all_objects.filter(
        tenant=tenant, sku=sku, is_preferred=True
    )
    assert preferred.count() == 1
    assert preferred.first().supplier_id == other.pk


def test_provision_agreement_converges_where_register_refuses(db, tenant, supplier, sku):
    """A re-runnable job must converge; a user action must be told."""
    SupplierProductAgreementService.register_agreement(
        tenant=tenant, supplier=supplier, sku=sku, agreed_unit_price=Decimal("10.00"),
    )
    with pytest.raises(ValidationError, match="already has an agreement"):
        SupplierProductAgreementService.register_agreement(
            tenant=tenant, supplier=supplier, sku=sku, agreed_unit_price=Decimal("12.00"),
        )
    agreement = SupplierProductAgreementService.provision_agreement(
        tenant=tenant, supplier=supplier, sku=sku, agreed_unit_price=Decimal("12.00"),
    )
    assert agreement.agreed_unit_price == Decimal("12.00")
    assert SupplierProductAgreement.all_objects.filter(tenant=tenant, sku=sku).count() == 1


# ---------------------------------------------------------------------------
# 4. Insurance authoring
# ---------------------------------------------------------------------------


@pytest.fixture
def plan(db, tenant):
    insurer = InsurerOnboardingService.onboard_insurer(
        tenant=tenant, code="GAP-INS", name="Gap Insurer"
    )
    scheme = InsurerOnboardingService.add_scheme(
        insurer=insurer, code="GAP-SCHEME", name="Corporate"
    )
    return InsurerOnboardingService.add_plan(scheme=scheme, code="GAP-PLAN", name="Gold")


@pytest.fixture
def patient(db, tenant, submitter):
    return Patient.all_objects.create(
        tenant=tenant, internal_reference_id="GAP-PAT-1", patient_number="NCD-0000001",
        first_name="Test", last_name="Patient",
    )


def test_authoring_against_a_production_insurer_is_refused(db, tenant, plan, reviewer):
    """A live payer's benefits are set by the payer, not authored locally."""
    insurer = plan.scheme.insurer
    InsurerOnboardingService.promote_to_production(
        insurer=insurer, adapter=Insurer.IntegrationAdapter.SHA,
        actor=reviewer, reason="contract signed",
    )
    plan.refresh_from_db()
    with pytest.raises(ValidationError, match="sandbox activity"):
        InsuranceBenefitService.define_benefit(plan=plan, category="OUTPATIENT_MEDICINE")


def test_an_uncovered_category_cannot_carry_a_limit(db, plan):
    with pytest.raises(ValidationError, match="not covered"):
        InsuranceBenefitService.define_benefit(
            plan=plan, category="OPTICAL", covered=False, benefit_limit="1000.00",
        )


def test_a_contradictory_product_exclusion_is_refused(db, tenant, plan, sku):
    """Excluding a product inside a category the plan already excludes."""
    InsuranceBenefitService.define_benefit(
        plan=plan, category="OUTPATIENT_MEDICINE", covered=False
    )
    with pytest.raises(ValidationError, match="contradictory"):
        InsuranceBenefitService.exclude_product(
            plan=plan, sku=sku, reason="not on formulary"
        )


def test_an_exclusion_inside_a_covered_category_is_allowed(db, tenant, plan, sku):
    """Excluding one brand from a covered category is a real rule."""
    InsuranceBenefitService.define_benefit(
        plan=plan, category="OUTPATIENT_MEDICINE", covered=True
    )
    exclusion = InsuranceBenefitService.exclude_product(
        plan=plan, sku=sku, reason="brand not on formulary"
    )
    assert exclusion.pk is not None
    assert InsuranceBenefitService.is_excluded(plan=plan, sku=sku) is True


def test_benefit_definition_is_idempotent(db, plan):
    first = InsuranceBenefitService.define_benefit(plan=plan, category="OUTPATIENT_MEDICINE")
    second = InsuranceBenefitService.define_benefit(plan=plan, category="OUTPATIENT_MEDICINE")
    assert first.pk == second.pk
    assert CoverageBenefit.all_objects.filter(plan=plan).count() == 1


def test_coverage_cannot_cross_a_tenant_boundary(db, tenant, plan, submitter):
    other_tenant = Tenant.objects.create(name="Other", slug="othergap")
    outsider = Patient.all_objects.create(
        tenant=other_tenant, internal_reference_id="OTHER-1", patient_number="NCD-9999999",
    )
    member = InsuranceMembershipService.register_member(
        tenant=tenant, membership_number="GAP-M-1", principal_name="Member One"
    )
    with pytest.raises(ValidationError, match="different tenants"):
        InsuranceMembershipService.enrol_patient(
            member=member, patient=outsider, plan=plan,
            valid_from=TODAY, valid_to=TODAY + timedelta(days=365),
        )


def test_enrolment_is_idempotent_and_creates_no_claims(db, tenant, plan, patient):
    from apps.insurance.models import PrescriptionClaim

    member = InsuranceMembershipService.register_member(
        tenant=tenant, membership_number="GAP-M-2", principal_name="Member Two"
    )
    first = InsuranceMembershipService.enrol_patient(
        member=member, patient=patient, plan=plan,
        valid_from=TODAY, valid_to=TODAY + timedelta(days=365),
    )
    second = InsuranceMembershipService.enrol_patient(
        member=member, patient=patient, plan=plan,
        valid_from=TODAY, valid_to=TODAY + timedelta(days=365),
    )
    assert first.pk == second.pk
    assert PrescriptionClaim.all_objects.filter(tenant=tenant).count() == 0


def test_coverage_cannot_end_before_it_begins(db, tenant, plan, patient):
    member = InsuranceMembershipService.register_member(
        tenant=tenant, membership_number="GAP-M-3", principal_name="Member Three"
    )
    with pytest.raises(ValidationError, match="cannot end before"):
        InsuranceMembershipService.enrol_patient(
            member=member, patient=patient, plan=plan,
            valid_from=TODAY, valid_to=TODAY - timedelta(days=1),
        )


def test_a_coverage_limit_starts_fully_available(db, tenant, plan, patient):
    """Remaining is derived, so cover cannot arrive partly consumed."""
    member = InsuranceMembershipService.register_member(
        tenant=tenant, membership_number="GAP-M-4", principal_name="Member Four"
    )
    coverage = InsuranceMembershipService.enrol_patient(
        member=member, patient=patient, plan=plan,
        valid_from=TODAY, valid_to=TODAY + timedelta(days=365),
    )
    limit = InsuranceMembershipService.set_coverage_limit(
        coverage=coverage, category="OUTPATIENT_PHARMACY", total_limit="50000.00",
    )
    assert limit.remaining_amount == Decimal("50000.00")
    assert limit.used_amount == Decimal("0.00")


def test_the_principal_carries_dependent_code_zero(db, tenant, plan, patient):
    member = InsuranceMembershipService.register_member(
        tenant=tenant, membership_number="GAP-M-5", principal_name="Member Five"
    )
    with pytest.raises(ValidationError, match="dependent code 00"):
        InsuranceMembershipService.enrol_patient(
            member=member, patient=patient, plan=plan,
            valid_from=TODAY, valid_to=TODAY + timedelta(days=365),
            relationship=InsuranceCoverage.Relationship.SELF, dependent_code="01",
        )


# ---------------------------------------------------------------------------
# 5. Scoped price books
# ---------------------------------------------------------------------------


def test_a_branch_scoped_book_requires_a_branch(db, tenant):
    book = PriceBookService.create_book(
        tenant=tenant, code="PB-BRANCH", name="Branch book",
        scope_type=PriceBook.ScopeType.BRANCH,
    )
    with pytest.raises(ValidationError, match="requires a branch"):
        PriceBookService.assign_scope(book=book)


def test_entries_cannot_be_written_to_an_active_version(
    db, tenant, sku, submitter, reviewer
):
    """An ACTIVE version is what customers were charged."""
    version = PriceBookService.publish_priced_book(
        tenant=tenant, code="PB-ACTIVE", name="Retail",
        prices={sku: Decimal("100.00")}, author=submitter, approver=reviewer,
        effective_from=TODAY,
    )
    assert version.status == PriceBookVersion.Status.ACTIVE
    with pytest.raises(ValidationError, match="cannot be edited"):
        PriceBookService.add_or_update_entry(
            version=version, sku=sku, unit_price=Decimal("50.00")
        )


def test_the_approver_must_differ_from_the_author(db, tenant, sku, submitter):
    book = PriceBookService.create_book(tenant=tenant, code="PB-SOD", name="SoD book")
    version = PriceBookService.create_draft(
        book=book, effective_from=TODAY, actor=submitter
    )
    PriceBookService.add_or_update_entry(
        version=version, sku=sku, unit_price=Decimal("10.00")
    )
    PriceBookService.submit(version=version, actor=submitter)
    with pytest.raises(PermissionDenied, match="must differ"):
        PriceBookService.approve(version=version, approver=submitter)


def test_an_empty_version_cannot_be_submitted(db, tenant, submitter):
    """An empty active book contributes no candidate and fails silently."""
    book = PriceBookService.create_book(tenant=tenant, code="PB-EMPTY", name="Empty")
    version = PriceBookService.create_draft(
        book=book, effective_from=TODAY, actor=submitter
    )
    with pytest.raises(ValidationError, match="no price entries"):
        PriceBookService.submit(version=version, actor=submitter)


def test_activation_supersedes_the_incumbent(db, tenant, sku, submitter, reviewer):
    """Two ACTIVE versions would make resolution fatally ambiguous."""
    book = PriceBookService.create_book(tenant=tenant, code="PB-SUP", name="Supersede")
    for price in (Decimal("10.00"), Decimal("12.00")):
        version = PriceBookService.create_draft(
            book=book, effective_from=TODAY, actor=submitter
        )
        PriceBookService.add_or_update_entry(version=version, sku=sku, unit_price=price)
        PriceBookService.submit(version=version, actor=submitter)
        PriceBookService.approve(version=version, approver=reviewer)
        PriceBookService.activate(version=version, actor=reviewer)

    active = PriceBookVersion.all_objects.filter(
        tenant=tenant, price_book=book, status=PriceBookVersion.Status.ACTIVE
    )
    assert active.count() == 1


def test_negative_prices_are_refused_and_prices_quantize(db, tenant, sku, submitter):
    book = PriceBookService.create_book(tenant=tenant, code="PB-Q", name="Quantize")
    version = PriceBookService.create_draft(
        book=book, effective_from=TODAY, actor=submitter
    )
    with pytest.raises(ValidationError, match="cannot be negative"):
        PriceBookService.add_or_update_entry(
            version=version, sku=sku, unit_price=Decimal("-1.00")
        )
    entry = PriceBookService.add_or_update_entry(
        version=version, sku=sku, unit_price="10.999"
    )
    assert entry.unit_price == Decimal("11.00")


def test_a_zero_price_is_permitted_and_preserved(db, tenant, sku, submitter):
    """Zero is a real price -- a free line -- and must not be confused with absent."""
    book = PriceBookService.create_book(tenant=tenant, code="PB-ZERO", name="Zero")
    version = PriceBookService.create_draft(
        book=book, effective_from=TODAY, actor=submitter
    )
    entry = PriceBookService.add_or_update_entry(
        version=version, sku=sku, unit_price=Decimal("0.00")
    )
    assert entry.unit_price == Decimal("0.00")


def test_scoped_books_carry_distinct_resolution_ranks(db):
    """Precedence is owned by PriceResolutionService; assert it stays total."""
    from apps.pricing.resolution import PriceSource, ranks_are_unique

    assert ranks_are_unique()
    ranks = dict(PriceSource.all_sources())
    # Insurance beats branch, branch beats tenant. This ordering is what the
    # scoped books rely on, so a change to it should break here.
    assert ranks["INSURANCE_TARIFF"] < ranks["BRANCH_PRICE"] < ranks["TENANT_PRICE"]
    assert ranks["BRANCH_PROMOTION"] < ranks["BRANCH_PRICE"]
    assert ranks["CUSTOMER_CONTRACT"] < ranks["BRANCH_PRICE"]
    assert ranks["MANUAL_OVERRIDE"] < ranks["INSURANCE_TARIFF"]


def test_publishing_is_idempotent(db, tenant, sku, submitter, reviewer):
    first = PriceBookService.publish_priced_book(
        tenant=tenant, code="PB-IDEM", name="Idempotent",
        prices={sku: Decimal("10.00")}, author=submitter, approver=reviewer,
        effective_from=TODAY,
    )
    second = PriceBookService.publish_priced_book(
        tenant=tenant, code="PB-IDEM", name="Idempotent",
        prices={sku: Decimal("10.00")}, author=submitter, approver=reviewer,
        effective_from=TODAY,
    )
    assert first.pk == second.pk
    assert PriceBook.all_objects.filter(tenant=tenant, code="PB-IDEM").count() == 1
    assert PriceBookEntry.all_objects.filter(tenant=tenant, version=first).count() == 1
