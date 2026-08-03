"""Provisioning services for master data that previously had no write path.

These services became necessary because five domains -- organisations, sites,
storage areas, manufacturers, practitioners and insurers -- had models and
governance rules but no way to create a record except direct ORM access, which
enforced none of them.

The tests are mostly about refusal and about defaults, because that is where
the rules live: a practitioner who starts verified, an insurer that starts in
production, or a quarantine bay that does not quarantine would each be a safety
problem rather than a cosmetic one.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditEvent
from apps.identity.models import AttributePolicy, Role, User, UserRole
from apps.insurance.models import Insurer
from apps.insurance.services.onboarding import InsurerOnboardingService
from apps.inventory.location_services import InventoryLocationProvisioningService
from apps.inventory.models import InventoryLocation
from apps.medicines.services import ManufacturerRegistrationService
from apps.organizations.models import Department, DepartmentMembership
from apps.organizations.services import (
    DEPARTMENT_METADATA_KEY,
    DepartmentProvisioningService,
    OrganizationProvisioningService,
    SiteProvisioningService,
)
from apps.practitioners.models import Practitioner
from apps.practitioners.services import PractitionerRegistrationService
from apps.tenancy.models import Tenant

LocationType = InventoryLocation.LocationType


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Test Chemists", slug="test-chemists")


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name="Other Chemists", slug="other-chemists")


@pytest.fixture
def actor(db, tenant):
    return User.objects.create(username="provisioner", tenant=tenant, is_superuser=True)


@pytest.fixture
def org(db, tenant):
    return OrganizationProvisioningService.provision_organization(
        tenant=tenant, code="NC-HQ", name="Nairobi Chemists Ltd"
    )


# --------------------------------------------------------------------------
# Organisations and sites
# --------------------------------------------------------------------------


def test_provisioning_an_organization_is_idempotent(db, tenant):
    a = OrganizationProvisioningService.provision_organization(
        tenant=tenant, code="NC-HQ", name="Nairobi Chemists Ltd"
    )
    b = OrganizationProvisioningService.provision_organization(
        tenant=tenant, code="NC-HQ", name="Nairobi Chemists Ltd"
    )
    assert a.pk == b.pk


def test_organization_requires_code_and_name(db, tenant):
    with pytest.raises(ValidationError, match="code"):
        OrganizationProvisioningService.provision_organization(tenant=tenant, code="", name="X")
    with pytest.raises(ValidationError, match="name"):
        OrganizationProvisioningService.provision_organization(tenant=tenant, code="X", name="")


def test_site_provisioning_is_idempotent(db, tenant, org):
    a = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-CBD", name="CBD Branch"
    )
    b = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-CBD", name="CBD Branch"
    )
    assert a.pk == b.pk


def test_site_cannot_cross_a_tenant_boundary(db, tenant, other_tenant, org):
    """The model would reject this on save; the service names the mistake."""
    with pytest.raises(ValidationError, match="different tenant"):
        SiteProvisioningService.provision_site(
            tenant=other_tenant, organization=org, code="X-1", name="Wrong Tenant Branch"
        )


def test_unknown_site_type_is_refused_unless_deliberate(db, tenant, org):
    with pytest.raises(ValidationError, match="Unrecognised site type"):
        SiteProvisioningService.provision_site(
            tenant=tenant, organization=org, code="NC-TYPO", name="Typo",
            site_type="WAREHOSE",
        )
    deliberate = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-NEW", name="New kind",
        site_type="MOBILE_UNIT", allow_unknown_type=True,
    )
    assert deliberate.location_type == "MOBILE_UNIT"


def test_contact_details_are_written_under_stable_keys(db, tenant, org, actor):
    site = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-WL", name="Westlands Branch"
    )
    SiteProvisioningService.set_contact_details(
        site=site, phone="+254700000001", email="westlands@example.test",
        operating_hours={"mon_fri": "08:00-20:00"}, manager=actor,
    )
    site.refresh_from_db()
    assert site.metadata["contact"]["phone"] == "+254700000001"
    assert site.metadata["contact"]["email"] == "westlands@example.test"
    assert site.metadata["operating_hours"]["mon_fri"] == "08:00-20:00"
    assert site.metadata["manager"]["username"] == "provisioner"


def test_a_site_cannot_supply_itself(db, tenant, org):
    site = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-1", name="Branch One"
    )
    with pytest.raises(ValidationError, match="its own supplying warehouse"):
        SiteProvisioningService.link_supplying_warehouse(site=site, warehouse=site)


def test_warehouse_linkage_records_the_supplier(db, tenant, org):
    branch = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-2", name="Branch Two"
    )
    warehouse = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-WH", name="Central Warehouse",
        site_type="WAREHOUSE",
    )
    SiteProvisioningService.link_supplying_warehouse(site=branch, warehouse=warehouse)
    branch.refresh_from_db()
    assert branch.metadata["supplying_warehouse"]["code"] == "NC-WH"


def test_closing_a_site_preserves_the_row(db, tenant, org, actor):
    """History points at the site, so closure is a status change."""
    site = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-3", name="Branch Three"
    )
    SiteProvisioningService.close_site(site=site, actor=actor, reason="lease ended")
    site.refresh_from_db()
    assert site.status == "CLOSED"
    assert site.metadata["closure"]["reason"] == "lease ended"


def test_closing_a_site_requires_an_actor_and_reason(db, tenant, org, actor):
    site = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-4", name="Branch Four"
    )
    with pytest.raises(PermissionDenied):
        SiteProvisioningService.close_site(site=site, actor=None, reason="x")
    with pytest.raises(ValidationError, match="reason"):
        SiteProvisioningService.close_site(site=site, actor=actor, reason="")


# --------------------------------------------------------------------------
# Storage areas
# --------------------------------------------------------------------------


@pytest.fixture
def branch(db, tenant, org):
    return SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-MAIN", name="Main Branch"
    )


@pytest.mark.parametrize(
    "kind,flag",
    [
        (LocationType.QUARANTINE, "quarantine_capability"),
        (LocationType.COLD_ROOM, "cold_chain_capability"),
        (LocationType.CONTROLLED_VAULT, "controlled_drug_capability"),
        (LocationType.RETURNS, "returns_capability"),
        (LocationType.DAMAGED, "damaged_goods_capability"),
        (LocationType.EXPIRED, "expiry_hold_capability"),
    ],
)
def test_capabilities_are_derived_from_storage_type(db, tenant, branch, kind, flag):
    """A quarantine bay that does not quarantine is a safety problem."""
    loc = InventoryLocationProvisioningService.provision_location(
        tenant=tenant, branch=branch, location_code=f"L-{kind}", name=str(kind),
        location_type=kind,
    )
    assert getattr(loc, flag) is True


def test_implied_capability_cannot_be_cleared(db, tenant, branch):
    with pytest.raises(ValidationError, match="cannot be cleared"):
        InventoryLocationProvisioningService.provision_location(
            tenant=tenant, branch=branch, location_code="L-BAD", name="Fake quarantine",
            location_type=LocationType.QUARANTINE,
            extra_capabilities={"quarantine_capability": False},
        )


def test_restricted_types_are_flagged_restricted(db, tenant, branch):
    for kind in (LocationType.QUARANTINE, LocationType.DAMAGED, LocationType.EXPIRED,
                 LocationType.CONTROLLED_VAULT):
        loc = InventoryLocationProvisioningService.provision_location(
            tenant=tenant, branch=branch, location_code=f"R-{kind}", name=str(kind),
            location_type=kind,
        )
        assert loc.restricted_flag is True


def test_storage_location_is_idempotent(db, tenant, branch):
    a = InventoryLocationProvisioningService.provision_location(
        tenant=tenant, branch=branch, location_code="L-1", name="Store",
    )
    b = InventoryLocationProvisioningService.provision_location(
        tenant=tenant, branch=branch, location_code="L-1", name="Store",
    )
    assert a.pk == b.pk


def test_unknown_storage_type_is_refused(db, tenant, branch):
    with pytest.raises(ValidationError, match="Unknown storage type"):
        InventoryLocationProvisioningService.provision_location(
            tenant=tenant, branch=branch, location_code="L-X", name="X",
            location_type="BASEMENT",
        )


def test_standard_layout_always_includes_the_non_optional_areas(db, tenant, branch):
    """Receiving, quarantine and failure areas are not optional."""
    layout = InventoryLocationProvisioningService.provision_standard_layout(
        tenant=tenant, branch=branch, prefix="MAIN",
    )
    assert {"main", "dispensary", "receiving", "quarantine", "returns", "damaged",
            "expired"} <= set(layout)
    assert "controlled" not in layout
    assert "cold_chain" not in layout


def test_standard_layout_adds_licensed_areas_on_request(db, tenant, branch):
    layout = InventoryLocationProvisioningService.provision_standard_layout(
        tenant=tenant, branch=branch, prefix="FULL",
        include_controlled=True, include_cold_chain=True,
    )
    assert layout["controlled"].controlled_drug_capability is True
    assert layout["cold_chain"].cold_chain_capability is True


def test_nesting_across_branches_is_refused(db, tenant, org, branch):
    other_branch = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code="NC-OTHER", name="Other Branch"
    )
    parent = InventoryLocationProvisioningService.provision_location(
        tenant=tenant, branch=branch, location_code="P-1", name="Parent",
    )
    with pytest.raises(ValidationError, match="another branch"):
        InventoryLocationProvisioningService.provision_location(
            tenant=tenant, branch=other_branch, location_code="C-1", name="Child",
            parent_location=parent,
        )


# --------------------------------------------------------------------------
# Manufacturers
# --------------------------------------------------------------------------


def test_tenant_manufacturer_satisfies_the_scope_constraint(db, tenant):
    m = ManufacturerRegistrationService.register_tenant_manufacturer(
        tenant=tenant, code="MFR-1", legal_name="Nairobi Pharma Ltd", country="KE"
    )
    assert m.is_global is False and m.tenant_id == tenant.id


def test_global_manufacturer_satisfies_the_scope_constraint(db):
    m = ManufacturerRegistrationService.register_global_manufacturer(
        code="GBL-1", legal_name="Global Pharma Inc", country="IN"
    )
    assert m.is_global is True and m.tenant_id is None


def test_manufacturer_registration_is_idempotent(db, tenant):
    a = ManufacturerRegistrationService.register_tenant_manufacturer(
        tenant=tenant, code="MFR-2", legal_name="Repeat Ltd"
    )
    b = ManufacturerRegistrationService.register_tenant_manufacturer(
        tenant=tenant, code="MFR-2", legal_name="Repeat Ltd"
    )
    assert a.pk == b.pk


def test_tenant_manufacturer_requires_a_tenant(db):
    with pytest.raises(ValidationError, match="requires a tenant"):
        ManufacturerRegistrationService.register_tenant_manufacturer(
            tenant=None, code="X", legal_name="Y"
        )


def test_deactivating_a_manufacturer_requires_actor_and_reason(db, tenant, actor):
    m = ManufacturerRegistrationService.register_tenant_manufacturer(
        tenant=tenant, code="MFR-3", legal_name="Closing Ltd"
    )
    with pytest.raises(PermissionDenied):
        ManufacturerRegistrationService.deactivate(manufacturer=m, actor=None, reason="x")
    ManufacturerRegistrationService.deactivate(manufacturer=m, actor=actor, reason="ceased trading")
    m.refresh_from_db()
    assert m.is_active is False


# --------------------------------------------------------------------------
# Practitioners
# --------------------------------------------------------------------------


def test_a_registered_practitioner_starts_unverified(db, tenant):
    """Registration records a claim; verification is a separate act."""
    p = PractitionerRegistrationService.register_practitioner(
        tenant=tenant, first_name="Amina", last_name="Wanjiru", profession="DOCTOR",
        registration_number="KMPDC-1001",
    )
    assert p.verification_state == "UNVERIFIED"
    assert p.controlled_medicine_authority is False
    assert p.metadata["verification_basis"] == "MANUAL_INTERNAL_VERIFICATION"


def test_practitioner_registration_is_idempotent_on_registration_number(db, tenant):
    a = PractitionerRegistrationService.register_practitioner(
        tenant=tenant, first_name="Brian", last_name="Otieno", profession="DOCTOR",
        registration_number="KMPDC-1002",
    )
    b = PractitionerRegistrationService.register_practitioner(
        tenant=tenant, first_name="Brian", last_name="Otieno", profession="DOCTOR",
        registration_number="KMPDC-1002",
    )
    assert a.pk == b.pk


def test_unknown_profession_is_refused(db, tenant):
    with pytest.raises(ValidationError, match="Unknown profession"):
        PractitionerRegistrationService.register_practitioner(
            tenant=tenant, first_name="X", last_name="Y", profession="WIZARD",
        )


def test_licence_cannot_expire_before_issue(db, tenant):
    with pytest.raises(ValidationError, match="expire before"):
        PractitionerRegistrationService.register_practitioner(
            tenant=tenant, first_name="X", last_name="Y", profession="DOCTOR",
            licence_issue_date=date(2026, 1, 1), licence_expiry_date=date(2025, 1, 1),
        )


def test_controlled_authority_refused_for_unverified_practitioner(db, tenant, actor):
    """Authority over controlled drugs cannot rest on an unchecked claim."""
    p = PractitionerRegistrationService.register_practitioner(
        tenant=tenant, first_name="Cynthia", last_name="Mwangi", profession="DOCTOR",
        registration_number="KMPDC-1003",
    )
    with pytest.raises(ValidationError, match="requires a verified practitioner"):
        PractitionerRegistrationService.grant_controlled_medicine_authority(
            practitioner=p, actor=actor, reason="senior prescriber",
        )


def test_controlled_authority_refused_for_expired_licence(db, tenant, actor):
    p = PractitionerRegistrationService.register_practitioner(
        tenant=tenant, first_name="Daniel", last_name="Kiptoo", profession="DOCTOR",
        registration_number="KMPDC-1004",
        licence_expiry_date=date.today() - timedelta(days=1),
    )
    Practitioner.all_objects.filter(pk=p.pk).update(verification_state="VERIFIED")
    p.refresh_from_db()
    with pytest.raises(ValidationError, match="expired"):
        PractitionerRegistrationService.grant_controlled_medicine_authority(
            practitioner=p, actor=actor, reason="senior prescriber",
        )


def test_controlled_authority_granted_and_revoked_with_attribution(db, tenant, actor):
    p = PractitionerRegistrationService.register_practitioner(
        tenant=tenant, first_name="Esther", last_name="Njeri", profession="DOCTOR",
        registration_number="KMPDC-1005",
        licence_expiry_date=date.today() + timedelta(days=365),
    )
    Practitioner.all_objects.filter(pk=p.pk).update(verification_state="VERIFIED")
    p.refresh_from_db()

    PractitionerRegistrationService.grant_controlled_medicine_authority(
        practitioner=p, actor=actor, reason="authorised prescriber", evidence_reference="REF-1",
    )
    p.refresh_from_db()
    assert p.controlled_medicine_authority is True
    assert p.metadata["controlled_authority"]["granted_by"] == "provisioner"

    PractitionerRegistrationService.revoke_controlled_medicine_authority(
        practitioner=p, actor=actor, reason="left the organisation",
    )
    p.refresh_from_db()
    assert p.controlled_medicine_authority is False

    # Both transitions must be on the audit trail. Asserting only on the model
    # field would let a broken log_audit call through on whichever path the
    # test happened not to exercise.
    actions = set(
        AuditEvent.all_objects.filter(
            tenant_id=tenant.id, object_id=str(p.pk)
        ).values_list("action", flat=True)
    )
    assert "PRACTITIONER_CONTROLLED_AUTHORITY_GRANTED" in actions
    assert "PRACTITIONER_CONTROLLED_AUTHORITY_REVOKED" in actions


# --------------------------------------------------------------------------
# Insurers
# --------------------------------------------------------------------------


def test_an_onboarded_insurer_starts_in_sandbox_with_the_fake_adapter(db, tenant):
    """Creating a counterparty must not create a route to sending real claims."""
    ins = InsurerOnboardingService.onboard_insurer(
        tenant=tenant, code="SHA", name="Social Health Authority",
        insurer_type=Insurer.InsurerType.PUBLIC,
    )
    assert ins.environment == Insurer.Environment.SANDBOX
    assert ins.integration_adapter == Insurer.IntegrationAdapter.FAKE


def test_insurer_onboarding_is_idempotent(db, tenant):
    a = InsurerOnboardingService.onboard_insurer(tenant=tenant, code="AAR", name="AAR Insurance")
    b = InsurerOnboardingService.onboard_insurer(tenant=tenant, code="AAR", name="AAR Insurance")
    assert a.pk == b.pk


def test_promotion_to_production_requires_actor_reason_and_live_adapter(db, tenant, actor):
    ins = InsurerOnboardingService.onboard_insurer(tenant=tenant, code="JUB", name="Jubilee")

    with pytest.raises(PermissionDenied):
        InsurerOnboardingService.promote_to_production(
            insurer=ins, adapter=Insurer.IntegrationAdapter.SHA, actor=None, reason="go live",
        )
    with pytest.raises(ValidationError, match="reason"):
        InsurerOnboardingService.promote_to_production(
            insurer=ins, adapter=Insurer.IntegrationAdapter.SHA, actor=actor, reason="",
        )
    with pytest.raises(ValidationError, match="not a live adapter"):
        InsurerOnboardingService.promote_to_production(
            insurer=ins, adapter=Insurer.IntegrationAdapter.FAKE, actor=actor, reason="go live",
        )

    InsurerOnboardingService.promote_to_production(
        insurer=ins, adapter=Insurer.IntegrationAdapter.SHA, actor=actor, reason="contract signed",
    )
    ins.refresh_from_db()
    assert ins.environment == Insurer.Environment.PRODUCTION


def test_scheme_and_plan_hierarchy_is_idempotent(db, tenant):
    ins = InsurerOnboardingService.onboard_insurer(tenant=tenant, code="MIN", name="Minet")
    s1 = InsurerOnboardingService.add_scheme(insurer=ins, code="CORP", name="Corporate")
    s2 = InsurerOnboardingService.add_scheme(insurer=ins, code="CORP", name="Corporate")
    assert s1.pk == s2.pk

    p1 = InsurerOnboardingService.add_plan(scheme=s1, code="GOLD", name="Gold")
    p2 = InsurerOnboardingService.add_plan(scheme=s1, code="GOLD", name="Gold")
    assert p1.pk == p2.pk
    assert p1.scheme_id == s1.pk


def test_suspending_an_insurer_keeps_the_relationship(db, tenant, actor):
    ins = InsurerOnboardingService.onboard_insurer(tenant=tenant, code="OLD", name="Old Mutual")
    InsurerOnboardingService.suspend_insurer(insurer=ins, actor=actor, reason="contract lapsed")
    ins.refresh_from_db()
    assert ins.status == Insurer.Status.SUSPENDED


# --------------------------------------------------------------------------
# Departments
#
# A department is an organisational unit, not a permission. The first test
# below is the one that matters: if it ever fails, there are two independent
# paths to a capability and no single answer to "what can this person do?".
# --------------------------------------------------------------------------


def test_department_membership_grants_no_capabilities(db, tenant, branch):
    """The whole design rests on this. Membership must never widen access."""
    member = User.objects.create(username="counter-staff", tenant=tenant)
    dispensary = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="MAIN-DISP", name="Dispensary",
        department_type=Department.TYPE_DISPENSARY,
    )
    before = member.effective_capabilities(tenant_id=tenant.id)
    DepartmentProvisioningService.assign_member(department=dispensary, user=member)
    member.refresh_from_db()
    after = member.effective_capabilities(tenant_id=tenant.id)

    assert before == after == set()
    assert member.has_capability("dispensing.dispense", tenant_id=tenant.id) is False


def test_attribute_policy_can_deny_on_the_mirrored_department(db, tenant, branch):
    """Departments narrow access through the ABAC that already exists."""
    role = Role.objects.create(
        tenant=tenant, code="PHARM", name="Pharmacist",
        capabilities=["dispensing.dispense"],
    )
    member = User.objects.create(username="pharmacist-a", tenant=tenant)
    UserRole.objects.create(tenant=tenant, user=member, role=role)

    retail = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="MAIN-RETAIL", name="Retail counter",
        department_type=Department.TYPE_RETAIL,
    )
    DepartmentProvisioningService.assign_member(
        department=retail, user=member, is_primary=True,
    )
    member.refresh_from_db()
    assert member.metadata[DEPARTMENT_METADATA_KEY] == "MAIN-RETAIL"
    assert member.has_capability("dispensing.dispense", tenant_id=tenant.id) is True

    # A policy denying the capability to retail staff must now bite, using the
    # mirrored key and no new mechanism.
    AttributePolicy.objects.create(
        tenant=tenant, code="NO-DISPENSE-AT-RETAIL", capability="dispensing.dispense",
        effect=AttributePolicy.EFFECT_DENY,
        conditions={"user_metadata": {DEPARTMENT_METADATA_KEY: "MAIN-RETAIL"}},
    )
    member.refresh_from_db()
    assert member.has_capability("dispensing.dispense", tenant_id=tenant.id) is False


def test_removing_a_member_clears_the_mirrored_department(db, tenant, branch, actor):
    """A stale department would keep satisfying a policy after they left it."""
    member = User.objects.create(username="mover", tenant=tenant)
    dept = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="MAIN-STORES", name="Stores",
        department_type=Department.TYPE_STORES,
    )
    DepartmentProvisioningService.assign_member(department=dept, user=member, is_primary=True)
    member.refresh_from_db()
    assert member.metadata[DEPARTMENT_METADATA_KEY] == "MAIN-STORES"

    DepartmentProvisioningService.remove_member(
        department=dept, user=member, actor=actor, reason="transferred",
    )
    member.refresh_from_db()
    assert DEPARTMENT_METADATA_KEY not in member.metadata


def test_department_provisioning_is_idempotent(db, tenant, branch):
    a = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-1", name="Dispensary",
    )
    b = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-1", name="Dispensary",
    )
    assert a.pk == b.pk


def test_membership_assignment_is_idempotent(db, tenant, branch):
    member = User.objects.create(username="repeat-member", tenant=tenant)
    dept = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-2", name="Dispensary",
    )
    a = DepartmentProvisioningService.assign_member(department=dept, user=member)
    b = DepartmentProvisioningService.assign_member(department=dept, user=member)
    assert a.pk == b.pk


def test_department_cannot_cross_a_tenant_boundary(db, tenant, other_tenant, branch):
    with pytest.raises(ValidationError, match="different tenant"):
        DepartmentProvisioningService.provision_department(
            tenant=other_tenant, site=branch, code="D-X", name="Wrong tenant",
        )


def test_user_cannot_join_a_department_in_another_tenant(db, tenant, other_tenant, branch):
    outsider = User.objects.create(username="outsider", tenant=other_tenant)
    dept = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-3", name="Dispensary",
    )
    with pytest.raises(ValidationError, match="their own tenant"):
        DepartmentProvisioningService.assign_member(department=dept, user=outsider)


def test_unknown_department_type_is_refused(db, tenant, branch):
    with pytest.raises(ValidationError, match="Unknown department type"):
        DepartmentProvisioningService.provision_department(
            tenant=tenant, site=branch, code="D-4", name="X", department_type="CANTEEN",
        )


def test_only_one_primary_department_per_user(db, tenant, branch):
    """Switching primary demotes the old one rather than hitting the constraint."""
    member = User.objects.create(username="dual-role", tenant=tenant)
    first = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-5", name="Dispensary",
    )
    second = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-6", name="Retail", department_type=Department.TYPE_RETAIL,
    )
    DepartmentProvisioningService.assign_member(department=first, user=member, is_primary=True)
    DepartmentProvisioningService.assign_member(department=second, user=member, is_primary=True)

    primaries = DepartmentMembership.all_objects.filter(
        tenant=tenant, user=member, is_primary=True, is_active=True
    )
    assert primaries.count() == 1
    assert primaries.first().department_id == second.pk
    member.refresh_from_db()
    assert member.metadata[DEPARTMENT_METADATA_KEY] == "D-6"


def test_primary_requires_existing_membership(db, tenant, branch):
    member = User.objects.create(username="not-a-member", tenant=tenant)
    dept = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-7", name="Dispensary",
    )
    with pytest.raises(ValidationError, match="not an active member"):
        DepartmentProvisioningService.set_primary_department(user=member, department=dept)


def test_closing_a_department_refuses_while_staff_remain(db, tenant, branch, actor):
    member = User.objects.create(username="still-there", tenant=tenant)
    dept = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-8", name="Dispensary",
    )
    DepartmentProvisioningService.assign_member(department=dept, user=member)

    with pytest.raises(ValidationError, match="still has 1 active member"):
        DepartmentProvisioningService.close_department(
            department=dept, actor=actor, reason="merged into retail",
        )

    DepartmentProvisioningService.remove_member(
        department=dept, user=member, actor=actor, reason="reassigned",
    )
    DepartmentProvisioningService.close_department(
        department=dept, actor=actor, reason="merged into retail",
    )
    dept.refresh_from_db()
    assert dept.status == "CLOSED"


def test_a_closed_department_cannot_take_members(db, tenant, branch, actor):
    member = User.objects.create(username="late-joiner", tenant=tenant)
    dept = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-9", name="Dispensary",
    )
    DepartmentProvisioningService.close_department(
        department=dept, actor=actor, reason="closed",
    )
    with pytest.raises(ValidationError, match="cannot take members"):
        DepartmentProvisioningService.assign_member(department=dept, user=member)


def test_removal_and_closure_require_actor_and_reason(db, tenant, branch, actor):
    dept = DepartmentProvisioningService.provision_department(
        tenant=tenant, site=branch, code="D-10", name="Dispensary",
    )
    with pytest.raises(PermissionDenied):
        DepartmentProvisioningService.close_department(department=dept, actor=None, reason="x")
    with pytest.raises(ValidationError, match="reason"):
        DepartmentProvisioningService.close_department(department=dept, actor=actor, reason="")


def test_standard_departments_cover_a_working_site(db, tenant, branch):
    made = DepartmentProvisioningService.provision_standard_departments(
        tenant=tenant, site=branch, prefix="MAIN",
    )
    assert {"dispensary", "retail", "stores", "administration"} == set(made)
    assert "wholesale" not in made
    assert "cold_chain" not in made

    licensed = DepartmentProvisioningService.provision_standard_departments(
        tenant=tenant, site=branch, prefix="FULL",
        include_wholesale=True, include_cold_chain=True,
    )
    assert licensed["wholesale"].department_type == Department.TYPE_WHOLESALE
    assert licensed["cold_chain"].department_type == Department.TYPE_COLD_CHAIN
