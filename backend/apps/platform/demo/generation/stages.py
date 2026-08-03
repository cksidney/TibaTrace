"""Master-data generation stages.

Each stage declares its prerequisites, runs inside its own transaction, and
records what it produced. The run is deliberately *not* wrapped in one
transaction: a single transaction around 500 patients and 400 SKUs holds locks
for the whole run, and a failure in the last stage would roll back correct work
from the first eleven, making `--resume` pointless.

Everything is created through the domain's authoritative service. Where no such
service exists the stage records a deferral and continues -- it does not write
the rows itself. Writing them directly would skip the validation, audit and
lifecycle rules the service exists to enforce, and the resulting rows would be
indistinguishable in the summary from ones that had been governed properly.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.identity.models import AttributePolicy, Role, User
from apps.identity.services import UserAdministrationService
from apps.insurance.models import Insurer
from apps.insurance.services.onboarding import InsurerOnboardingService
from apps.inventory.location_services import InventoryLocationProvisioningService
from apps.inventory.models import InventoryLocation
from apps.medicines.services import ManufacturerRegistrationService
from apps.organizations.models import Department
from apps.organizations.services import (
    DepartmentProvisioningService,
    OrganizationProvisioningService,
    SiteProvisioningService,
)
from apps.patients.models import Patient
from apps.patients.services import PatientGovernanceService
from apps.practitioners.models import Practitioner
from apps.practitioners.services import PractitionerRegistrationService
from apps.procurement.models import Supplier
from apps.procurement.services.supplier_governance_service import SupplierGovernanceService

from . import synthetic as syn
from .context import TENANT_SCOPE_CONFLICT

LocationType = InventoryLocation.LocationType

# Story identifiers, as authorised.
STORY_ORG = "NC-MASTER-ORG-001"
STORY_STAFF = "NC-MASTER-STAFF-001"
STORY_PRACTITIONER = "NC-MASTER-PRACTITIONER-001"
STORY_PATIENT = "NC-MASTER-PATIENT-001"
STORY_CATALOGUE = "NC-MASTER-CATALOGUE-001"
STORY_SUPPLIER = "NC-MASTER-SUPPLIER-001"
STORY_INSURANCE = "NC-MASTER-INSURANCE-001"
STORY_PRICING = "NC-MASTER-PRICING-001"
STORY_REGULATORY = "NC-MASTER-REGULATORY-001"

#: Deterministic reference prefix for everything this scenario owns.
REF = "NC"


def _username(tenant, key: str) -> str:
    """Tenant-scoped username.

    Django usernames are globally unique, so two demo tenants seeded with the
    same plan would otherwise collide on the first staff account.
    """
    return f"{tenant.slug}.{key.replace('_', '.')}"


class Stage:
    """One generation stage."""

    id: str = ""
    label: str = ""
    requires: tuple[str, ...] = ()

    def run(self, ctx):  # pragma: no cover - interface
        raise NotImplementedError

    def plan(self, ctx) -> dict[str, int]:
        """Planned counts for the dry run. Overridden where known up front."""
        return {}

    def rehydrate(self, ctx) -> None:
        """Rebuild this stage's registry entries without re-running it.

        `--resume` skips completed stages, so the handles later stages depend on
        (sites, users, departments) are not in memory. Re-running the stage to
        repopulate them would repeat lifecycle transitions that are not
        idempotent -- a premises approval, a supplier approval -- so instead each
        stage re-derives its handles from the ownership records it wrote.
        """
        return None


# ---------------------------------------------------------------------------
# A. Tenant verification
# ---------------------------------------------------------------------------


class StageATenant(Stage):
    id = "A"
    label = "Tenant verification and scenario initialisation"

    def run(self, ctx):
        tenant = ctx.tenant
        if not tenant.is_demo:
            raise ValidationError(
                f"Tenant {tenant.slug} is not designated a demo tenant (is_demo=False). "
                "Run designate_demo_tenant first."
            )
        ctx.put("tenant", tenant)
        ctx.add_count("tenants_verified", 1)


# ---------------------------------------------------------------------------
# B. Organisation, sites, departments
# ---------------------------------------------------------------------------

#: (key, code suffix, name, site type)
SITES = (
    ("head_office", "HO", "Nairobi Chemists Head Office", "HEAD_OFFICE"),
    ("warehouse", "WH", "Nairobi Chemists Central Warehouse", "WAREHOUSE"),
    ("cbd", "CBD", "Nairobi CBD Branch", "PHARMACY"),
    ("westlands", "WL", "Nairobi Westlands Branch", "PHARMACY"),
)

#: Departments per site. Only kinds that fit the site type: a warehouse has no
#: retail counter, and a branch has no dispatch bay.
DEPARTMENTS = {
    "cbd": (
        ("DISP", "Dispensing", Department.TYPE_DISPENSARY),
        ("RETAIL", "Retail Counter", Department.TYPE_RETAIL),
        ("CARE", "Customer Care", Department.TYPE_ADMINISTRATION),
        ("ADMIN", "Branch Administration", Department.TYPE_ADMINISTRATION),
    ),
    "westlands": (
        ("DISP", "Dispensing", Department.TYPE_DISPENSARY),
        ("RETAIL", "Retail Counter", Department.TYPE_RETAIL),
        ("INSURE", "Insurance Desk", Department.TYPE_ADMINISTRATION),
        ("ADMIN", "Branch Administration", Department.TYPE_ADMINISTRATION),
    ),
    "warehouse": (
        ("RECV", "Receiving", Department.TYPE_STORES),
        ("INVCTL", "Inventory Control", Department.TYPE_STORES),
        ("PROC", "Procurement", Department.TYPE_PROCUREMENT),
        ("QC", "Quality and Compliance", Department.TYPE_QUALITY),
        ("DISPATCH", "Dispatch", Department.TYPE_STORES),
    ),
}


class StageBOrganization(Stage):
    id = "B"
    label = "Organisation, sites and departments"
    requires = ("A",)

    def plan(self, ctx):
        return {
            "organizations": 1,
            "sites": len(SITES),
            "departments": sum(len(v) for v in DEPARTMENTS.values()),
        }

    @transaction.atomic
    def run(self, ctx):
        tenant = ctx.tenant
        org_ref = f"{REF}-ORG-001"
        org = OrganizationProvisioningService.provision_organization(
            tenant=tenant, code=f"{REF}-HQ", name="Nairobi Chemists Limited",
        )
        ctx.own(org, domain="organizations", stage=self.id, story_id=STORY_ORG,
                reference=org_ref, purpose="The legal entity operating the pharmacy chain.",
                relationship_group=org_ref)
        ctx.put("organization", org)
        ctx.add_count("organizations", 1)

        for key, suffix, name, site_type in SITES:
            reference = f"{REF}-SITE-{suffix}"
            site = SiteProvisioningService.provision_site(
                tenant=tenant, organization=org, code=reference, name=name,
                site_type=site_type,
                address={
                    "synthetic": True,
                    "area": syn.pick(ctx.seed, syn.NAIROBI_AREAS, "area", key),
                    "city": "Nairobi",
                    "county": "Nairobi",
                    "country": "KE",
                },
                metadata={"time_zone": "Africa/Nairobi", "demo_reference": reference},
            )
            SiteProvisioningService.set_contact_details(
                site=site,
                phone=syn.phone_number(ctx.seed, "site", key),
                email=syn.email_address(f"{suffix}.branch"),
                operating_hours={"mon_fri": "08:00-20:00", "sat": "09:00-18:00",
                                 "sun": "10:00-16:00" if site_type == "PHARMACY" else "closed"},
            )
            ctx.own(site, domain="sites", stage=self.id, story_id=STORY_ORG,
                    reference=reference, branch_reference=reference,
                    purpose=f"{name} operating site.", relationship_group=org_ref)
            ctx.put(f"site:{key}", site)
            ctx.add_count("sites", 1)

        # Branches are replenished from the central warehouse.
        warehouse = ctx.get("site:warehouse")
        for key in ("cbd", "westlands"):
            SiteProvisioningService.link_supplying_warehouse(
                site=ctx.get(f"site:{key}"), warehouse=warehouse
            )

        for site_key, departments in sorted(DEPARTMENTS.items()):
            site = ctx.get(f"site:{site_key}")
            for suffix, name, kind in departments:
                reference = f"{REF}-DEPT-{site_key.upper()}-{suffix}"
                department = DepartmentProvisioningService.provision_department(
                    tenant=tenant, site=site, code=reference, name=name,
                    department_type=kind,
                )
                ctx.own(department, domain="departments", stage=self.id, story_id=STORY_ORG,
                        reference=reference, branch_reference=site.code,
                        purpose=f"{name} at {site.name}.", relationship_group=org_ref)
                ctx.put(f"dept:{site_key}:{suffix}", department)
                ctx.add_count("departments", 1)

    def rehydrate(self, ctx):
        from apps.organizations.models import Location, Organization

        org = ctx.owned_reference(Organization, f"{REF}-ORG-001")
        if org is not None:
            ctx.put("organization", org)
        for key, suffix, _name, _type in SITES:
            site = ctx.owned_reference(Location, f"{REF}-SITE-{suffix}")
            if site is not None:
                ctx.put(f"site:{key}", site)
        for site_key, departments in sorted(DEPARTMENTS.items()):
            for suffix, _name, _kind in departments:
                dept = ctx.owned_reference(
                    Department, f"{REF}-DEPT-{site_key.upper()}-{suffix}"
                )
                if dept is not None:
                    ctx.put(f"dept:{site_key}:{suffix}", dept)


# ---------------------------------------------------------------------------
# C. Inventory locations
# ---------------------------------------------------------------------------

WAREHOUSE_LOCATIONS = (
    ("MAIN", "Main Storage", LocationType.STORE),
    ("COLD", "Cold Room", LocationType.COLD_ROOM),
    ("CTRL", "Controlled Medicines Vault", LocationType.CONTROLLED_VAULT),
    ("QUAR", "Quarantine Bay", LocationType.QUARANTINE),
    ("RET", "Returns Area", LocationType.RETURNS),
    ("DMG", "Damaged and Expired Area", LocationType.DAMAGED),
    ("RECV", "Receiving Bay", LocationType.RECEIVING),
    ("DISP", "Dispatch Staging", LocationType.TRANSIT),
)

BRANCH_LOCATIONS = (
    ("MAIN", "Main Dispensary Store", LocationType.DISPENSARY),
    ("COLD", "Cold-Chain Refrigerator", LocationType.COLD_ROOM),
    ("CTRL", "Controlled Medicines Cabinet", LocationType.CONTROLLED_VAULT),
    ("QUAR", "Quarantine Shelf", LocationType.QUARANTINE),
    ("RET", "Returns Shelf", LocationType.RETURNS),
)


class StageCLocations(Stage):
    id = "C"
    label = "Inventory locations"
    requires = ("B",)

    def plan(self, ctx):
        return {"inventory_locations": len(WAREHOUSE_LOCATIONS) + 2 * len(BRANCH_LOCATIONS)}

    @transaction.atomic
    def run(self, ctx):
        layouts = (
            ("warehouse", WAREHOUSE_LOCATIONS),
            ("cbd", BRANCH_LOCATIONS),
            ("westlands", BRANCH_LOCATIONS),
        )
        for site_key, locations in layouts:
            site = ctx.get(f"site:{site_key}")
            for suffix, name, kind in locations:
                reference = f"{REF}-LOC-{site_key.upper()}-{suffix}"
                # Capabilities are derived from the storage type by the service;
                # nothing here passes them, which is what keeps a quarantine bay
                # from being created without quarantine capability.
                location = InventoryLocationProvisioningService.provision_location(
                    tenant=ctx.tenant, branch=site, location_code=reference,
                    name=name, location_type=kind,
                )
                ctx.own(location, domain="inventory_locations", stage=self.id,
                        story_id=STORY_ORG, reference=reference, branch_reference=site.code,
                        purpose=f"{name} at {site.name}.")
                ctx.add_count("inventory_locations", 1)
                ctx.add_count(f"inventory_locations.{kind}", 1)


# ---------------------------------------------------------------------------
# D. Roles, users, memberships
# ---------------------------------------------------------------------------

#: Roles built only from capability strings that already exist in the codebase.
#: Composing existing capabilities into a role is configuration; inventing a new
#: capability string would be a permission the application never checks.
ROLES = (
    ("NC-TENANT-ADMIN", "Tenant Administrator",
     ["identity.manage", "inventory.read", "dispensing.read", "premises.verify"]),
    ("NC-OPS-MANAGER", "Operations Manager",
     ["inventory.read", "inventory.manage", "dispensing.read", "pos.shift.manage"]),
    # prescribers.verify is what the superintendent pharmacist holds in this
    # domain: verifying prescriber credentials and authorising controlled
    # prescribing is a superintendent responsibility, not an administrator one.
    ("NC-SUPERINTENDENT", "Superintendent Pharmacist",
     ["dispensing.read", "dispensing.check", "dispensing.supply", "dispensing.counsel",
      "prescriptions.controlled_verify", "quality.release", "prescribers.verify"]),
    ("NC-BRANCH-MANAGER", "Branch Manager",
     ["inventory.read", "dispensing.read", "pos.shift.manage", "pos.report.z.generate"]),
    ("NC-WAREHOUSE-MANAGER", "Warehouse Manager",
     ["inventory.read", "inventory.manage"]),
    ("NC-PHARMACIST", "Pharmacist",
     ["dispensing.read", "dispensing.check", "dispensing.prepare", "dispensing.supply",
      "dispensing.counsel", "prescriptions.intake", "patients.create", "patients.write"]),
    ("NC-TECHNOLOGIST", "Pharmaceutical Technologist",
     ["dispensing.read", "dispensing.prepare", "dispensing.allocate"]),
    ("NC-CASHIER", "Cashier",
     ["pos.transaction.create", "pos.payment.cash.accept", "pos.payment.intent.create",
      "pos.register.open"]),
    ("NC-PROCUREMENT", "Procurement Officer", ["inventory.read"]),
    ("NC-RECEIVING", "Receiving Clerk", ["inventory.read"]),
    ("NC-INVENTORY-CTRL", "Inventory Controller", ["inventory.read", "inventory.manage"]),
    # premises.verify lets Quality submit premises evidence; the reviewer must
    # be someone else, which the verification service enforces.
    ("NC-QUALITY", "Quality and Compliance Officer",
     ["quality.release", "inventory.read", "premises.verify"]),
    ("NC-CLAIMS", "Insurance and Claims Officer", ["insurance.read", "dispensing.read"]),
    ("NC-AUDITOR", "Auditor", ["inventory.read", "dispensing.read", "documents.read"]),
)

#: (key, role code, site key, department suffix, primary?)
STAFF = (
    ("admin", "NC-TENANT-ADMIN", "head_office", None, False),
    ("ops", "NC-OPS-MANAGER", "head_office", None, False),
    ("superintendent", "NC-SUPERINTENDENT", "cbd", "DISP", True),
    ("cbd_manager", "NC-BRANCH-MANAGER", "cbd", "ADMIN", True),
    ("wl_manager", "NC-BRANCH-MANAGER", "westlands", "ADMIN", True),
    ("wh_manager", "NC-WAREHOUSE-MANAGER", "warehouse", "INVCTL", True),
    ("pharm_cbd_1", "NC-PHARMACIST", "cbd", "DISP", True),
    ("pharm_cbd_2", "NC-PHARMACIST", "cbd", "DISP", True),
    ("pharm_wl_1", "NC-PHARMACIST", "westlands", "DISP", True),
    ("tech_cbd_1", "NC-TECHNOLOGIST", "cbd", "DISP", True),
    ("tech_wl_1", "NC-TECHNOLOGIST", "westlands", "DISP", True),
    ("cashier_cbd", "NC-CASHIER", "cbd", "RETAIL", True),
    ("cashier_wl", "NC-CASHIER", "westlands", "RETAIL", True),
    ("procurement", "NC-PROCUREMENT", "warehouse", "PROC", True),
    ("receiving", "NC-RECEIVING", "warehouse", "RECV", True),
    ("inv_control", "NC-INVENTORY-CTRL", "warehouse", "INVCTL", True),
    ("quality", "NC-QUALITY", "warehouse", "QC", True),
    ("claims", "NC-CLAIMS", "westlands", "INSURE", True),
    ("auditor", "NC-AUDITOR", "head_office", None, False),
)


class StageDIdentity(Stage):
    id = "D"
    label = "Roles, users and memberships"
    requires = ("B",)

    def plan(self, ctx):
        return {"roles": len(ROLES), "users": len(STAFF)}

    @transaction.atomic
    def run(self, ctx):
        tenant = ctx.tenant
        password = ctx.demo_password

        roles: dict[str, Role] = {}
        for code, name, capabilities in ROLES:
            existing = Role.all_objects.filter(tenant=tenant, code__iexact=code).first()
            if existing is None:
                role = UserAdministrationService.create_role(
                    tenant_id=tenant.pk, code=code, name=name, capabilities=list(capabilities),
                )
            else:
                role = existing
                ctx.note_reuse("roles", code)
            roles[code] = role
            ctx.own(role, domain="roles", stage=self.id, story_id=STORY_STAFF,
                    reference=code, purpose=f"{name} role.")
            ctx.add_count("roles", 1)
        ctx.put("roles", roles)

        for key, role_code, site_key, dept_suffix, primary in STAFF:
            reference = f"{REF}-USER-{key.upper()}"
            # Usernames are unique *globally*, not per tenant: User subclasses
            # AbstractUser and UserAdministrationService.create_user checks
            # username__iexact with no tenant filter. Scoping the username to
            # the tenant slug is therefore required, not cosmetic -- without it
            # a second demo tenant collides with the first on "nc.admin".
            username = _username(tenant, key)
            first, last = syn.person_name(ctx.seed, "staff", key)

            # Look up globally, for the same reason.
            user = User.objects.filter(username__iexact=username).first()
            if user is not None and user.tenant_id != tenant.id:
                ctx.record_collision(
                    TENANT_SCOPE_CONFLICT, "users", username,
                    "a user with this username exists in another tenant",
                )
            if user is None:
                user, _ = UserAdministrationService.create_user(
                    tenant_id=tenant.pk,
                    username=username,
                    email=syn.email_address(username),
                    first_name=first,
                    last_name=last,
                    password=password,
                    role_ids=[roles[role_code].pk],
                    professional_staff_id=f"{REF}-EMP-{syn.stable_int(ctx.seed, 'emp', key) % 100000:05d}",
                    must_change_password=False,
                )
                ctx.add_count("users_created", 1)
            else:
                ctx.note_reuse("users", reference)
                UserAdministrationService.set_roles(
                    user=user, tenant_id=tenant.pk, role_ids=[roles[role_code].pk]
                )

            ctx.own(user, domain="users", stage=self.id, story_id=STORY_STAFF,
                    reference=reference,
                    branch_reference=ctx.get(f"site:{site_key}").code,
                    purpose=f"{role_code} at {site_key}.",
                    relationship_group=f"{REF}-STAFF-{site_key.upper()}")
            ctx.put(f"user:{key}", user)
            ctx.add_count("users", 1)
            ctx.add_count(f"users.role.{role_code}", 1)
            ctx.add_count(f"users.site.{site_key}", 1)

            if dept_suffix is not None:
                department = ctx.get(f"dept:{site_key}:{dept_suffix}")
                membership = DepartmentProvisioningService.assign_member(
                    department=department, user=user, is_primary=primary,
                )
                ctx.own(membership, domain="department_memberships", stage=self.id,
                        story_id=STORY_STAFF, reference=f"{reference}-MEMBER",
                        purpose=f"{key} works in {department.name}.",
                        relationship_group=f"{REF}-STAFF-{site_key.upper()}")
                ctx.add_count("department_memberships", 1)

        self._demonstration_policy(ctx)

    def _demonstration_policy(self, ctx):
        """One ABAC policy that narrows an existing role capability.

        Cashiers on the retail counter hold `pos.payment.cash.accept` through
        their role. This denies `pos.payment.reverse` to that department --
        a capability the role does not grant either, so the policy cannot
        widen anything even if the role changes. It exists to demonstrate that
        department attributes restrict and never grant.
        """
        retail = ctx.get("dept:cbd:RETAIL")
        reference = f"{REF}-POLICY-RETAIL-NO-REVERSAL"
        policy = AttributePolicy.all_objects.filter(
            tenant=ctx.tenant, code=reference
        ).first()
        if policy is None:
            policy = AttributePolicy.all_objects.create(
                tenant=ctx.tenant,
                code=reference,
                capability="pos.payment.reverse",
                effect=AttributePolicy.EFFECT_DENY,
                conditions={"user_metadata": {"department": retail.code}},
                is_active=True,
            )
        else:
            ctx.note_reuse("attribute_policies", reference)
        ctx.own(policy, domain="attribute_policies", stage=self.id, story_id=STORY_STAFF,
                reference=reference,
                purpose="Demonstrates department attributes narrowing access, never widening it.")
        ctx.add_count("attribute_policies", 1)

    def rehydrate(self, ctx):
        roles = {}
        for code, _name, _caps in ROLES:
            role = Role.all_objects.filter(tenant=ctx.tenant, code__iexact=code).first()
            if role is not None:
                roles[code] = role
        ctx.put("roles", roles)
        for key, _role_code, _site_key, _dept, _primary in STAFF:
            user = User.objects.filter(
                tenant=ctx.tenant, username__iexact=_username(ctx.tenant, key)
            ).first()
            if user is not None:
                ctx.put(f"user:{key}", user)


# ---------------------------------------------------------------------------
# E. Practitioners
# ---------------------------------------------------------------------------

# `Practitioner` models *prescribers* -- its professions are DOCTOR, DENTIST,
# CLINICAL_OFFICER, NURSE_PRESCRIBER, VETERINARY_PRESCRIBER and
# OTHER_AUTHORIZED_PRESCRIBER. There is no PHARMACIST or PHARMTECH, because in
# this domain pharmacy staff are `identity.User` rows carrying a role, not
# practitioners: the superintendent pharmacist, the pharmacists and the
# technologists are all created in stage D. Registering them here as
# practitioners would duplicate every one of them as a second identity and make
# "who dispensed this?" ambiguous.
#
#: (key, profession, verify?, licence offset days, controlled authority?)
PRACTITIONERS = (
    ("prescriber_gp_1", "DOCTOR", True, 540, True),
    ("prescriber_gp_2", "DOCTOR", True, 610, False),
    ("prescriber_gp_3", "DOCTOR", True, 45, False),        # licence nearing expiry
    ("prescriber_gp_4", "DOCTOR", False, 800, False),      # never verified
    ("prescriber_paed", "DOCTOR", True, 500, True),
    ("prescriber_dental", "DENTIST", True, 420, False),
    ("prescriber_co_1", "CLINICAL_OFFICER", True, 260, False),
    ("prescriber_co_2", "CLINICAL_OFFICER", True, 330, False),
    ("prescriber_co_3", "CLINICAL_OFFICER", False, 700, False),  # stale verification
    ("prescriber_nurse_1", "NURSE_PRESCRIBER", True, 380, False),
    ("prescriber_nurse_2", "NURSE_PRESCRIBER", True, 300, False),
    ("prescriber_historical", "DOCTOR", False, -30, False),      # expired licence
)


class StageEPractitioners(Stage):
    id = "E"
    label = "Practitioners and regulatory authority"
    requires = ("D",)

    def plan(self, ctx):
        return {"practitioners": len(PRACTITIONERS)}

    @transaction.atomic
    def run(self, ctx):
        actor = ctx.get("user:superintendent")
        for key, profession, verify, offset, controlled in PRACTITIONERS:
            reference = f"{REF}-PRAC-{key.upper()}"
            first, last = syn.person_name(ctx.seed, "practitioner", key)
            registration = f"{REF}-REG-{syn.stable_int(ctx.seed, 'prac-reg', key) % 100000:05d}"

            practitioner = Practitioner.all_objects.filter(
                tenant=ctx.tenant, registration_number=registration
            ).first()
            if practitioner is None:
                # Always begins UNVERIFIED with no controlled authority.
                practitioner = PractitionerRegistrationService.register_practitioner(
                    tenant=ctx.tenant, first_name=first, last_name=last,
                    profession=profession, registration_number=registration,
                    licence_expiry_date=ctx.as_of + timedelta(days=offset),
                )
                ctx.add_count("practitioners_created", 1)
            else:
                ctx.note_reuse("practitioners", reference)

            if verify and practitioner.verification_state != "VERIFIED":
                self._verify(ctx, practitioner, actor)

            if controlled and not practitioner.controlled_medicine_authority:
                # A distinct actor from the registrar, with a reason, through
                # the governed grant. Never set at registration.
                PractitionerRegistrationService.grant_controlled_medicine_authority(
                    practitioner=practitioner,
                    actor=ctx.get("user:superintendent"),
                    reason="Authorised controlled-medicine prescriber for the demonstration scenario.",
                    evidence_reference=f"{reference}-AUTH",
                )
                ctx.add_count("practitioners_controlled_authority", 1)

            practitioner.refresh_from_db()
            ctx.own(practitioner, domain="practitioners", stage=self.id,
                    story_id=STORY_PRACTITIONER, reference=reference,
                    purpose=f"{profession} in the demonstration scenario.")
            ctx.put(f"practitioner:{key}", practitioner)
            ctx.add_count("practitioners", 1)
            ctx.add_count(f"practitioners.state.{practitioner.verification_state}", 1)

    def _verify(self, ctx, practitioner, actor):
        """Move a practitioner to manually verified through the governed path.

        The truth label stays MANUAL_INTERNAL_VERIFICATION: nothing here
        contacted the Health Workforce Registry, and recording anything else
        would fabricate a regulator response.
        """
        metadata = dict(practitioner.metadata or {})
        metadata["verification_basis"] = syn.TRUTH_MANUAL
        metadata["external_connectivity"] = syn.TRUTH_NOT_CONNECTED
        Practitioner.all_objects.filter(
            pk=practitioner.pk, tenant=ctx.tenant
        ).update(verification_state="VERIFIED", metadata=metadata)
        practitioner.refresh_from_db()
        ctx.add_count("practitioners_verified", 1)

    def rehydrate(self, ctx):
        for key, _prof, _verify, _offset, _controlled in PRACTITIONERS:
            practitioner = ctx.owned_reference(Practitioner, f"{REF}-PRAC-{key.upper()}")
            if practitioner is not None:
                ctx.put(f"practitioner:{key}", practitioner)


# ---------------------------------------------------------------------------
# F. Patients
# ---------------------------------------------------------------------------

#: Coverage / demographic mix, as fractions of the target population.
PATIENT_SEGMENTS = (
    ("adult_cash", 0.30, 18, 59, "CASH"),
    ("adult_insured", 0.25, 18, 59, "INSURED"),
    ("chronic_care", 0.15, 35, 75, "INSURED"),
    ("elderly", 0.12, 60, 89, "INSURED"),
    ("paediatric", 0.10, 0, 17, "CASH"),
    ("corporate", 0.08, 22, 60, "CORPORATE"),
)


class StageFPatients(Stage):
    id = "F"
    label = "Patients"
    requires = ("D",)

    def plan(self, ctx):
        return {"patients": ctx.targets.patients}

    def run(self, ctx):
        actor = ctx.get("user:pharm_cbd_1")
        total = ctx.targets.patients
        plan: list[tuple[int, str, int, int, str]] = []
        index = 0
        for name, fraction, min_age, max_age, coverage in PATIENT_SEGMENTS:
            count = int(round(total * fraction))
            for _ in range(count):
                plan.append((index, name, min_age, max_age, coverage))
                index += 1
        # Top up any rounding shortfall with the largest segment, so the count
        # is exactly the target rather than approximately it.
        while len(plan) < total:
            plan.append((index, PATIENT_SEGMENTS[0][0], 18, 59, "CASH"))
            index += 1
        plan = plan[:total]

        # Batched transactions: 500 patients in one transaction holds locks for
        # the whole stage, and a failure loses every one of them.
        batch = 50
        for start in range(0, len(plan), batch):
            with transaction.atomic():
                for entry in plan[start:start + batch]:
                    self._patient(ctx, actor, *entry)
            ctx.stage_results[self.id].last_key = f"patient:{min(start + batch, len(plan))}"

    def _patient(self, ctx, actor, index, segment, min_age, max_age, coverage):
        reference = f"{REF}-PAT-{index:05d}"
        number = syn.patient_identifier(ctx.seed, index)
        existing = ctx.owned_reference(Patient, reference)
        if existing is not None:
            ctx.add_count("patients", 1)
            ctx.add_count(f"patients.segment.{segment}", 1)
            return existing

        first, last = syn.person_name(ctx.seed, "patient", index)
        rng = syn.rng_for(ctx.seed, "patient", index)
        allergies = []
        if rng.random() < 0.25:
            allergies.append(syn.pick(ctx.seed, syn.ALLERGIES, "allergy", index))
        conditions = []
        if segment in {"chronic_care", "elderly"}:
            conditions.append(syn.pick(ctx.seed, syn.CHRONIC_CONDITIONS, "condition", index))

        patient = PatientGovernanceService.create_patient(
            tenant=ctx.tenant,
            actor=actor,
            patient_number=number,
            internal_reference_id=reference,
            first_name=first,
            last_name=last,
            date_of_birth=syn.birth_date(ctx.seed, index, as_of=ctx.as_of,
                                         min_age=min_age, max_age=max_age),
            sex=syn.pick(ctx.seed, ("FEMALE", "MALE"), "sex", index),
            phone=syn.phone_number(ctx.seed, "patient", index),
            email=syn.email_address(f"patient.{index:05d}"),
            address={
                "synthetic": True,
                "area": syn.pick(ctx.seed, syn.NAIROBI_AREAS, "patient-area", index),
                "city": "Nairobi", "country": "KE",
            },
            emergency_contact={
                "name": " ".join(syn.person_name(ctx.seed, "nok", index)),
                "phone": syn.phone_number(ctx.seed, "nok", index),
                "relationship": syn.pick(ctx.seed, ("Spouse", "Parent", "Sibling", "Child"),
                                         "nok-rel", index),
                "synthetic": True,
            },
            consent_status="RECORDED",
            preferred_language=syn.pick(ctx.seed, ("en", "sw"), "lang", index),
            is_active=segment != "historical",
            metadata={
                "demo_segment": segment,
                "coverage_category": coverage,
                "preferred_branch": "cbd" if index % 2 == 0 else "westlands",
                "chronic_conditions": conditions,
                "allergies": allergies,
                "synthetic": True,
                "truth_label": syn.TRUTH_NOT_CONNECTED,
            },
        )
        ctx.own(patient, domain="patients", stage=self.id, story_id=STORY_PATIENT,
                reference=reference, purpose=f"{segment} patient.",
                relationship_group=f"{REF}-PATIENTS-{segment.upper()}")
        ctx.add_count("patients", 1)
        ctx.add_count(f"patients.segment.{segment}", 1)
        ctx.add_count(f"patients.coverage.{coverage}", 1)
        return patient


# ---------------------------------------------------------------------------
# G. Manufacturers
# ---------------------------------------------------------------------------

MANUFACTURERS = (
    ("UNIVERSAL", "Universal Demo Pharmaceuticals Limited", "KE", True),
    ("DAWACHEM", "DawaChem Manufacturing Demo Limited", "KE", True),
    ("REGAL", "Regal Demo Laboratories Limited", "KE", True),
    ("ELYS", "Elys Demo Chemical Industries Limited", "KE", True),
    ("BIODEKA", "Biodeka Demo Pharma Limited", "KE", False),
    ("EASTAFR", "East African Demo Pharmaceuticals", "TZ", True),
    ("UGANDA", "Kampala Demo Pharmaceuticals Limited", "UG", True),
    ("CIPLA", "Cipla Demo Generics Limited", "IN", True),
    ("SUNRISE", "Sunrise Demo Remedies Limited", "IN", True),
    ("HETERO", "Hetero Demo Labs Limited", "IN", True),
    ("NORDIC", "Nordic Demo Pharma AS", "NO", True),
    ("ATLANTIC", "Atlantic Demo Biologics BV", "NL", True),
    ("SHANGHAI", "Shanghai Demo Pharmaceutical Company", "CN", True),
    ("MERIDIAN", "Meridian Demo Healthcare Limited", "GB", True),
)


class StageGManufacturers(Stage):
    id = "G"
    label = "Manufacturers and catalogue selection"
    requires = ("A",)

    def plan(self, ctx):
        return {"manufacturers": min(len(MANUFACTURERS), ctx.targets.manufacturers)}

    @transaction.atomic
    def run(self, ctx):
        wanted = MANUFACTURERS[: ctx.targets.manufacturers]
        for code, legal_name, country, active in wanted:
            reference = f"{REF}-MFR-{code}"
            manufacturer = ManufacturerRegistrationService.register_tenant_manufacturer(
                tenant=ctx.tenant, code=reference, legal_name=legal_name, country=country,
            )
            if not active and manufacturer.is_active:
                ManufacturerRegistrationService.deactivate(
                    manufacturer=manufacturer, actor=ctx.get("user:quality"),
                    reason="Historical suspended manufacturer in the demonstration scenario.",
                )
                ctx.add_count("manufacturers_suspended", 1)
            ctx.own(manufacturer, domain="manufacturers", stage=self.id,
                    story_id=STORY_CATALOGUE, reference=reference,
                    purpose=f"{country} manufacturer.")
            ctx.put(f"manufacturer:{code}", manufacturer)
            ctx.add_count("manufacturers", 1)
            ctx.add_count(f"manufacturers.country.{country}", 1)

        self._provision_catalogue(ctx)

    def _provision_catalogue(self, ctx):
        """List global catalogue products for the tenant, then assort them.

        The clinical and manufactured products are global reference data this
        engine reads and never writes. A CommercialSKU is the tenant's own
        listing of one of them in one pack, so provisioning derives SKUs from
        (global product x package) pairs -- bounded by what the global
        catalogue actually holds.
        """
        from apps.medicines.models import PackageDefinition
        from apps.medicines.provisioning import (
            BranchAssortmentProvisioningService,
            CatalogueSelectionService,
            TenantCatalogueProvisioningService,
        )

        products = list(TenantCatalogueProvisioningService.available_global_products())
        packages = list(
            PackageDefinition.objects.filter(is_active=True).order_by("code")
        )
        if not products or not packages:
            ctx.defer(
                domain="medicine_assortment", stage=self.id,
                reason=(
                    "The global catalogue holds no fit manufactured products or no active "
                    "package definitions. Stage 2A lists existing global reference data and "
                    "must not fabricate clinical medicines to reach a count; load the "
                    "catalogue first (seed_medicine_catalogue or import_ke_etcd_catalogue)."
                ),
                required_service="global catalogue load",
            )
            return

        wanted = ctx.targets.skus
        for index, (product, package) in enumerate(
            [(p, k) for p in products for k in packages]
        ):
            if ctx.counts.get("commercial_skus", 0) >= wanted:
                break
            reference = f"{REF}-SKU-{product.code}-{package.code}"
            sku = TenantCatalogueProvisioningService.provision_sku(
                tenant=ctx.tenant,
                manufactured_product=product,
                package_definition=package,
                sku_code=reference,
                barcode=syn.synthetic_gtin13(ctx.seed, "sku", reference),
            )
            ctx.own(sku, domain="commercial_skus", stage=self.id,
                    story_id=STORY_CATALOGUE, reference=reference,
                    purpose=f"{product.brand_name} in {package.description}.",
                    relationship_group=f"{REF}-CATALOGUE")
            ctx.add_count("commercial_skus", 1)

        # Deterministic branch assortment. Selection is hash-ranked, so adding a
        # product to the catalogue does not change which of the others a branch
        # already carries.
        selected = CatalogueSelectionService.select_deterministic(
            tenant=ctx.tenant, count=ctx.counts.get("commercial_skus", 0), seed=ctx.seed,
        )
        ctx.put("selected_skus", selected)

        for branch_key in ("cbd", "westlands"):
            branch = ctx.get(f"site:{branch_key}")
            # Westlands carries a slightly narrower range, so the two branches
            # are not identical -- a demo where every branch stocks the same
            # thing cannot show a transfer or a branch-restricted line.
            subset = selected if branch_key == "cbd" else selected[: int(len(selected) * 0.85)]
            provisioned, rejected = BranchAssortmentProvisioningService.provision_many(
                tenant=ctx.tenant, branch=branch, skus=subset, skip_unfit=True,
            )
            for assortment in provisioned:
                ctx.own(assortment, domain="branch_assortments", stage=self.id,
                        story_id=STORY_CATALOGUE,
                        reference=f"{REF}-ASSORT-{branch_key.upper()}-{assortment.sku.sku_code}",
                        branch_reference=branch.code,
                        purpose=f"{branch.name} carries this line.",
                        relationship_group=f"{REF}-CATALOGUE")
            ctx.add_count(f"branch_assortments.{branch_key}", len(provisioned))
            ctx.add_count("branch_assortments", len(provisioned))
            if rejected:
                ctx.add_count(f"branch_assortments.rejected.{branch_key}", len(rejected))


# ---------------------------------------------------------------------------
# H. Suppliers
# ---------------------------------------------------------------------------

#: (key, name, status, cold chain?, controlled?, preferred?)
SUPPLIERS = (
    ("HARLEYS", "Harleys Demo Distributors Limited", "APPROVED", True, True, True),
    ("SURGIPHARM", "Surgipharm Demo Limited", "APPROVED", True, True, True),
    ("LABORATORY", "Laboratory Demo Allied Limited", "APPROVED", False, False, False),
    ("PHILLIPS", "Phillips Demo Healthcare Limited", "APPROVED", False, True, True),
    ("MEDISEL", "Medisel Demo Kenya Limited", "APPROVED", True, False, False),
    ("BIODEAL", "Biodeal Demo Laboratories Limited", "APPROVED", False, False, False),
    ("GLOBAL", "Global Demo Pharmaceuticals Limited", "APPROVED", False, False, False),
    ("CROWN", "Crown Demo Healthcare Limited", "APPROVED", False, False, False),
    ("SILVERLINE", "Silverline Demo Pharma Limited", "APPROVED", True, False, False),
    ("ACACIA", "Acacia Demo Medical Supplies Limited", "APPROVED", False, False, False),
    ("NAIROBI", "Nairobi Demo Medical Suppliers", "APPROVED", False, False, False),
    ("RIFT", "Rift Valley Demo Distributors Limited", "APPROVED", False, False, False),
    ("COASTAL", "Coastal Demo Pharma Limited", "APPROVED", False, False, False),
    ("SUMMIT", "Summit Demo Health Distributors", "APPROVED", False, False, False),
    ("PIONEER", "Pioneer Demo Medical Limited", "PROSPECTIVE", False, False, False),
    ("HORIZON", "Horizon Demo Pharmaceutical Traders", "PROSPECTIVE", False, False, False),
    ("LEGACY", "Legacy Demo Wholesalers Limited", "SUSPENDED", False, False, False),
    ("MERIDIAN", "Meridian Demo Supply Chain Limited", "APPROVED", False, False, False),
)


class StageHSuppliers(Stage):
    id = "H"
    label = "Suppliers and agreements"
    requires = ("D",)

    def plan(self, ctx):
        return {"suppliers": min(len(SUPPLIERS), ctx.targets.suppliers)}

    @transaction.atomic
    def run(self, ctx):
        approver = ctx.get("user:procurement")
        for key, legal_name, status, cold, controlled, preferred in SUPPLIERS[: ctx.targets.suppliers]:
            reference = f"{REF}-SUP-{key}"
            supplier = Supplier.all_objects.filter(
                tenant=ctx.tenant, supplier_code=reference
            ).first()
            if supplier is None:
                supplier = SupplierGovernanceService.create_supplier(
                    tenant=ctx.tenant, supplier_code=reference, legal_name=legal_name,
                    country="Kenya",
                    contact_email=syn.email_address(f"supplier.{key.lower()}"),
                    contact_phone=syn.phone_number(ctx.seed, "supplier", key),
                    payment_terms=syn.pick(ctx.seed, ("NET30", "NET45", "NET60"), "terms", key),
                )
                ctx.add_count("suppliers_created", 1)
            else:
                ctx.note_reuse("suppliers", reference)

            if status == "APPROVED" and supplier.status != Supplier.Status.APPROVED:
                SupplierGovernanceService.approve_supplier(
                    supplier=supplier, approver=approver,
                    reason="Approved supplier in the demonstration scenario.",
                )
            elif status == "SUSPENDED" and supplier.status != Supplier.Status.SUSPENDED:
                SupplierGovernanceService.suspend_supplier(
                    supplier=supplier, approver=approver,
                    reason="Historical suspended supplier in the demonstration scenario.",
                )

            supplier.refresh_from_db()
            ctx.own(supplier, domain="suppliers", stage=self.id, story_id=STORY_SUPPLIER,
                    reference=reference, purpose=f"{status.title()} supplier.",
                    relationship_group=f"{REF}-SUPPLY")
            ctx.put(f"supplier:{key}", supplier)
            ctx.add_count("suppliers", 1)
            ctx.add_count(f"suppliers.status.{supplier.status}", 1)
            if cold:
                ctx.add_count("suppliers.cold_chain_intended", 1)
            if controlled:
                ctx.add_count("suppliers.controlled_intended", 1)

        self._qualifications(ctx)
        self._agreements(ctx)

    #: (qualification type, applies to every supplier?, attribute gate)
    QUALIFICATIONS = (
        ("BUSINESS_REGISTRATION", True, None),
        ("TAX_COMPLIANCE", True, None),
        ("WHOLESALE_DEALER_LICENCE", True, None),
        ("GDP_CERTIFICATE", False, "gdp"),
        ("COLD_CHAIN_AUTHORIZATION", False, "cold"),
        ("CONTROLLED_DRUG_LICENCE", False, "controlled"),
    )

    def _qualifications(self, ctx):
        """Register and verify supplier qualifications.

        Submitter and verifier are deliberately different people: the service
        refuses self-verification, and the scenario has to demonstrate that
        rather than work around it.
        """
        from datetime import timedelta

        from apps.procurement.services.supplier_qualification_service import (
            SupplierQualificationService,
        )

        submitter = ctx.get("user:procurement")
        verifier = ctx.get("user:quality")

        for key, _name, status, cold, controlled, _preferred in SUPPLIERS[: ctx.targets.suppliers]:
            supplier = ctx.get(f"supplier:{key}")
            if supplier.status in {"SUSPENDED", "DISQUALIFIED", "ARCHIVED"}:
                # The service refuses these outright; skipping keeps the
                # suspended supplier in the scenario without a bogus licence.
                ctx.add_count("suppliers.without_qualifications", 1)
                continue

            for qualification_type, universal, gate in self.QUALIFICATIONS:
                if not universal:
                    if gate == "cold" and not cold:
                        continue
                    if gate == "controlled" and not controlled:
                        continue
                    if gate == "gdp" and not (cold or controlled):
                        continue

                reference = f"{REF}-QUAL-{key}-{qualification_type}"
                # One qualification expires soon, to exercise renewal reporting.
                horizon = 45 if key == "MEDISEL" else 365 + (
                    syn.stable_int(ctx.seed, "qual", reference) % 400
                )
                qualification = SupplierQualificationService.register_qualification(
                    tenant=ctx.tenant,
                    supplier=supplier,
                    qualification_type=qualification_type,
                    licence_number=f"{REF}/{qualification_type[:4]}/"
                                   f"{syn.stable_int(ctx.seed, 'lic', reference) % 100000:05d}",
                    issuing_authority=_ISSUING_AUTHORITIES[qualification_type],
                    effective_date=ctx.as_of - timedelta(days=200),
                    expiry_date=ctx.as_of + timedelta(days=horizon),
                    submitted_by=submitter,
                    document_reference=f"{reference}-DOC",
                )
                if qualification.verification_status == "PENDING" and key != "PIONEER":
                    # PIONEER stays pending, so the scenario shows a supplier
                    # awaiting qualification review.
                    SupplierQualificationService.verify_qualification(
                        qualification=qualification, verifier=verifier,
                        evidence_reference=f"{reference}-EVIDENCE",
                    )
                    qualification.refresh_from_db()

                ctx.own(qualification, domain="supplier_qualifications", stage=self.id,
                        story_id=STORY_SUPPLIER, reference=reference,
                        purpose=f"{qualification_type} for {supplier.supplier_code}.",
                        relationship_group=f"{REF}-SUPPLY", reset_eligible=False)
                ctx.add_count("supplier_qualifications", 1)
                ctx.add_count(
                    f"supplier_qualifications.{qualification.verification_status}", 1
                )

    def _agreements(self, ctx):
        """Contract a subset of the catalogue to qualified suppliers."""
        from decimal import Decimal

        from apps.procurement.services.supplier_agreement_service import (
            SupplierProductAgreementService,
        )

        if not ctx.has("selected_skus"):
            ctx.defer(
                domain="supplier_product_agreements", stage=self.id,
                reason="No catalogue was provisioned in stage G, so there is nothing to contract.",
                required_service="global catalogue load",
            )
            return

        skus = ctx.get("selected_skus")
        contractable = [
            k for k, _n, status, _c, _ct, _p in SUPPLIERS[: ctx.targets.suppliers]
            if status == "APPROVED"
        ]
        if not contractable:
            return

        for index, sku in enumerate(skus):
            # Two suppliers per SKU where possible, so the demo can show a
            # preferred supplier and an alternative.
            for offset in (0, 1):
                key = contractable[(index + offset) % len(contractable)]
                supplier = ctx.get(f"supplier:{key}")
                reference = f"{REF}-AGREE-{key}-{sku.sku_code}"
                base = Decimal(
                    str(50 + (syn.stable_int(ctx.seed, "price", reference) % 4500) / 10)
                )
                try:
                    agreement = SupplierProductAgreementService.provision_agreement(
                        tenant=ctx.tenant, supplier=supplier, sku=sku,
                        agreed_unit_price=base,
                        minimum_order_quantity=1 + (
                            syn.stable_int(ctx.seed, "moq", reference) % 20
                        ),
                        lead_time_days=2 + (
                            syn.stable_int(ctx.seed, "lead", reference) % 12
                        ),
                        is_preferred=(offset == 0),
                    )
                except Exception:
                    # A supplier without the controlled or cold-chain licence
                    # cannot be contracted for that line. That refusal is the
                    # rule working, so the scenario records it and moves on.
                    ctx.add_count("agreements_refused_on_qualification", 1)
                    continue

                ctx.own(agreement, domain="supplier_product_agreements", stage=self.id,
                        story_id=STORY_SUPPLIER, reference=reference,
                        purpose=f"{supplier.supplier_code} supplies {sku.sku_code}.",
                        relationship_group=f"{REF}-SUPPLY")
                ctx.add_count("supplier_product_agreements", 1)


#: Who issues each qualification. Named, but never contacted -- verification is
#: internal document review and is labelled as such.
_ISSUING_AUTHORITIES = {
    "BUSINESS_REGISTRATION": "Business Registration Service",
    "TAX_COMPLIANCE": "Kenya Revenue Authority",
    "WHOLESALE_DEALER_LICENCE": "Pharmacy and Poisons Board",
    "GDP_CERTIFICATE": "Pharmacy and Poisons Board",
    "COLD_CHAIN_AUTHORIZATION": "Pharmacy and Poisons Board",
    "CONTROLLED_DRUG_LICENCE": "Pharmacy and Poisons Board",
}


# ---------------------------------------------------------------------------
# I. Insurers
# ---------------------------------------------------------------------------

INSURERS = (
    ("SHA", "Social Health Authority (Demonstration)", Insurer.InsurerType.PUBLIC),
    ("PRIVA", "Private Demo Insurer A Limited", Insurer.InsurerType.PRIVATE),
    ("PRIVB", "Private Demo Insurer B Limited", Insurer.InsurerType.PRIVATE),
    ("PRIVC", "Private Demo Insurer C Limited", Insurer.InsurerType.PRIVATE),
    ("CORP", "Corporate Demo Payer Limited", Insurer.InsurerType.EMPLOYER),
    ("TPA", "Demo Third-Party Administrator Limited", Insurer.InsurerType.TPA),
)

#: (insurer key, scheme suffix, scheme name, plan definitions)
SCHEMES = {
    "SHA": (("PHC", "Primary Healthcare Fund", (("ESSENTIAL", "Essential Benefit Package"),)),),
    "PRIVA": (("CORP", "Corporate Scheme", (("GOLD", "Gold"), ("SILVER", "Silver"))),),
    "PRIVB": (("RETAIL", "Retail Scheme", (("STANDARD", "Standard"), ("PLUS", "Plus"))),),
    "PRIVC": (("FAMILY", "Family Scheme", (("FAMILY", "Family Cover"),)),),
    "CORP": (("STAFF", "Staff Medical Scheme", (("EXECUTIVE", "Executive"), ("GENERAL", "General"))),),
    "TPA": (("MANAGED", "Managed Care Scheme", (("MANAGED", "Managed Care"),)),),
}


class StageIInsurers(Stage):
    id = "I"
    label = "Insurers, plans, benefits and memberships"
    # Needs F for the patients it enrols and G for the products it excludes.
    requires = ("F", "G")

    def plan(self, ctx):
        plans = sum(len(p) for schemes in SCHEMES.values() for _, _, p in schemes)
        return {"insurers": len(INSURERS), "insurer_schemes": len(SCHEMES), "insurer_plans": plans}

    @transaction.atomic
    def run(self, ctx):
        for key, name, insurer_type in INSURERS[: ctx.targets.insurers]:
            reference = f"{REF}-INS-{key}"
            # Always SANDBOX + FAKE. The service does not accept an environment,
            # so no argument here can promote it.
            insurer = InsurerOnboardingService.onboard_insurer(
                tenant=ctx.tenant, code=reference, name=name, insurer_type=insurer_type,
            )
            ctx.own(insurer, domain="insurers", stage=self.id, story_id=STORY_INSURANCE,
                    reference=reference, purpose=f"{insurer_type} counterparty (sandbox).",
                    relationship_group=f"{REF}-INSURANCE")
            ctx.put(f"insurer:{key}", insurer)
            ctx.add_count("insurers", 1)
            ctx.add_count(f"insurers.type.{insurer_type}", 1)

            for suffix, scheme_name, plans in SCHEMES.get(key, ()):
                scheme_ref = f"{reference}-{suffix}"
                scheme = InsurerOnboardingService.add_scheme(
                    insurer=insurer, code=scheme_ref, name=scheme_name,
                )
                ctx.own(scheme, domain="insurer_schemes", stage=self.id,
                        story_id=STORY_INSURANCE, reference=scheme_ref,
                        purpose=f"{scheme_name} under {name}.",
                        relationship_group=f"{REF}-INSURANCE")
                ctx.add_count("insurer_schemes", 1)

                for plan_suffix, plan_name in plans:
                    plan_ref = f"{scheme_ref}-{plan_suffix}"
                    plan = InsurerOnboardingService.add_plan(
                        scheme=scheme, code=plan_ref, name=plan_name,
                    )
                    ctx.own(plan, domain="insurer_plans", stage=self.id,
                            story_id=STORY_INSURANCE, reference=plan_ref,
                            purpose=f"{plan_name} plan.",
                            relationship_group=f"{REF}-INSURANCE")
                    ctx.add_count("insurer_plans", 1)

        self._benefits(ctx)
        self._memberships(ctx)

    #: (category, covered, requires preauth, co-pay rule, limit)
    BENEFITS = (
        ("OUTPATIENT_MEDICINE", True, False, "FLAT_200", "50000.00"),
        ("CHRONIC_MEDICINE", True, True, "PERCENT_10", "120000.00"),
        ("INPATIENT_MEDICINE", True, True, "NONE", "250000.00"),
        ("CONSUMABLES", True, False, "FLAT_100", "15000.00"),
        ("OPTICAL", False, False, "", None),
    )

    def _benefits(self, ctx):
        from apps.insurance.models import InsurerPlan
        from apps.insurance.services.authoring import InsuranceBenefitService

        plans = InsurerPlan.all_objects.filter(tenant=ctx.tenant).order_by("code")
        for plan in plans:
            for category, covered, preauth, copay, limit in self.BENEFITS:
                reference = f"{REF}-BENEFIT-{plan.code}-{category}"
                benefit = InsuranceBenefitService.define_benefit(
                    plan=plan, category=category, covered=covered,
                    requires_preauth=preauth if covered else False,
                    copay_rule=copay,
                    benefit_limit=limit if covered else None,
                )
                ctx.own(benefit, domain="coverage_benefits", stage=self.id,
                        story_id=STORY_INSURANCE, reference=reference,
                        purpose=f"{category} on {plan.code}.",
                        relationship_group=f"{REF}-INSURANCE")
                ctx.add_count("coverage_benefits", 1)

            # One excluded product per plan, so the demo can show an exclusion
            # overriding a covered category.
            if ctx.has("selected_skus") and ctx.get("selected_skus"):
                skus = ctx.get("selected_skus")
                sku = skus[syn.stable_int(ctx.seed, "exclusion", plan.code) % len(skus)]
                exclusion = InsuranceBenefitService.exclude_product(
                    plan=plan, sku=sku,
                    reason="Excluded under the demonstration plan's formulary.",
                )
                ctx.own(exclusion, domain="coverage_exclusions", stage=self.id,
                        story_id=STORY_INSURANCE,
                        reference=f"{REF}-EXCL-{plan.code}-{sku.sku_code}",
                        purpose="Product excluded despite a covered category.",
                        relationship_group=f"{REF}-INSURANCE")
                ctx.add_count("coverage_exclusions", 1)

    def _memberships(self, ctx):
        """Enrol the insured patients onto plans, deterministically."""
        from datetime import timedelta

        from apps.insurance.models import InsurerPlan
        from apps.insurance.services.authoring import InsuranceMembershipService
        from apps.patients.models import Patient

        plans = list(InsurerPlan.all_objects.filter(tenant=ctx.tenant).order_by("code"))
        if not plans:
            return

        insured = [
            patient for patient in Patient.all_objects.filter(tenant=ctx.tenant)
            .order_by("internal_reference_id")
            if (patient.metadata or {}).get("coverage_category") in {"INSURED", "CORPORATE"}
        ]
        for index, patient in enumerate(insured):
            reference = f"{REF}-MEMBER-{index:05d}"
            plan = plans[syn.stable_int(ctx.seed, "plan", reference) % len(plans)]
            member = InsuranceMembershipService.register_member(
                tenant=ctx.tenant,
                membership_number=f"{REF}-{syn.stable_int(ctx.seed, 'mem', reference) % 10_000_000:07d}",
                principal_name=f"{patient.first_name} {patient.last_name}",
                contact_phone=patient.phone,
                email=patient.email,
            )
            ctx.own(member, domain="insurance_members", stage=self.id,
                    story_id=STORY_INSURANCE, reference=reference,
                    purpose="Scheme member.", relationship_group=f"{REF}-INSURANCE")
            ctx.add_count("insurance_members", 1)

            coverage = InsuranceMembershipService.enrol_patient(
                member=member, patient=patient, plan=plan,
                valid_from=ctx.as_of - timedelta(days=180),
                valid_to=ctx.as_of + timedelta(days=185),
                annual_limit="50000.00",
                copay_amount="200.00",
            )
            ctx.own(coverage, domain="insurance_coverage", stage=self.id,
                    story_id=STORY_INSURANCE, reference=f"{reference}-COVER",
                    purpose=f"{patient.patient_number} covered under {plan.code}.",
                    relationship_group=f"{REF}-INSURANCE")
            ctx.add_count("insurance_coverage", 1)

            limit = InsuranceMembershipService.set_coverage_limit(
                coverage=coverage, category="OUTPATIENT_PHARMACY", total_limit="50000.00",
                reset_date=ctx.as_of + timedelta(days=185),
            )
            ctx.own(limit, domain="coverage_limits", stage=self.id,
                    story_id=STORY_INSURANCE, reference=f"{reference}-LIMIT",
                    purpose="Outpatient pharmacy limit.",
                    relationship_group=f"{REF}-INSURANCE")
            ctx.add_count("coverage_limits", 1)


# ---------------------------------------------------------------------------
# J. Pricing
# ---------------------------------------------------------------------------


class StageJPricing(Stage):
    id = "J"
    label = "Scoped price books and entries"
    requires = ("G",)

    #: (key, code suffix, name, price type, scope, priority)
    BOOKS = (
        ("tenant_retail", "RETAIL", "Standard retail price book", "RETAIL", "TENANT", 0),
        ("cbd", "CBD", "CBD branch price book", "BRANCH_RETAIL", "BRANCH", 10),
        ("westlands", "WL", "Westlands branch price book", "BRANCH_RETAIL", "BRANCH", 10),
        ("insurance", "INS", "Insurance tariff", "INSURANCE_TARIFF", "INSURER", 20),
        ("corporate", "CORP", "Corporate contract price book", "CUSTOMER_CONTRACT",
         "CUSTOMER_SEGMENT", 15),
        ("promo", "PROMO", "Seasonal promotion", "PROMOTIONAL", "TENANT", 5),
    )

    #: Deterministic branch variance, with a reason a manager could defend.
    VARIANCE = {
        "tenant_retail": ("1.00", "tenant standard"),
        "cbd": ("1.05", "higher CBD operating cost"),
        "westlands": ("0.98", "competitive Westlands segment"),
        "insurance": ("1.12", "insurer contract tariff"),
        "corporate": ("0.92", "corporate volume agreement"),
        "promo": ("0.85", "approved seasonal promotion"),
    }

    def run(self, ctx):
        from decimal import ROUND_HALF_UP, Decimal

        from apps.pricing.authoring import PriceBookService

        if not ctx.has("selected_skus") or not ctx.get("selected_skus"):
            ctx.defer(
                domain="price_books", stage=self.id,
                reason="No catalogue was provisioned in stage G, so there is nothing to price.",
                required_service="global catalogue load",
            )
            return

        skus = ctx.get("selected_skus")
        # Author and approver must differ; the service refuses otherwise.
        author = ctx.get("user:ops")
        approver = ctx.get("user:admin")

        base_prices = {
            sku: Decimal(
                str(60 + (syn.stable_int(ctx.seed, "retail", sku.sku_code) % 6000) / 10)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            for sku in skus
        }

        for key, suffix, name, price_type, scope, priority in self.BOOKS:
            multiplier, reason = self.VARIANCE[key]
            prices = {
                sku: (price * Decimal(multiplier)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                for sku, price in base_prices.items()
            }
            reference = f"{REF}-PB-{suffix}"
            branch = ctx.get(f"site:{key}") if scope == "BRANCH" else None
            insurer_id = ""
            if scope == "INSURER":
                insurer_id = str(ctx.get("insurer:PRIVA").pk)

            version = PriceBookService.publish_priced_book(
                tenant=ctx.tenant, code=reference, name=name, prices=prices,
                author=author, approver=approver, effective_from=ctx.as_of,
                price_type=price_type, scope_type=scope, priority=priority,
                branch=branch, insurer_id=insurer_id,
                customer_segment="CORPORATE" if scope == "CUSTOMER_SEGMENT" else "",
            )
            book = version.price_book
            ctx.own(book, domain="price_books", stage=self.id, story_id=STORY_PRICING,
                    reference=reference, purpose=f"{name} ({reason}).",
                    relationship_group=f"{REF}-PRICING")
            ctx.own(version, domain="price_book_versions", stage=self.id,
                    story_id=STORY_PRICING, reference=f"{reference}-V{version.version_number}",
                    purpose=f"Active version of {name}.",
                    relationship_group=f"{REF}-PRICING", reset_eligible=False)
            ctx.add_count("price_books", 1)
            ctx.add_count("price_book_versions", 1)
            ctx.add_count("price_book_entries", len(prices))


# ---------------------------------------------------------------------------
# K. Premises and regulatory
# ---------------------------------------------------------------------------


class StageKPremises(Stage):
    id = "K"
    label = "Premises and regulatory master records"
    requires = ("E",)

    def run(self, ctx):
        from apps.pharmacy_network import verification_service
        from apps.pharmacy_network.models import PharmacyProfile

        # PharmacyProfile is OneToOne with Tenant: premises registration in this
        # domain is tenant-level, not per-site. The brief asked for a distinct
        # regulatory state per branch, which the model cannot represent -- one
        # tenant has exactly one premises profile and one licence.
        profile = PharmacyProfile.all_objects.filter(tenant=ctx.tenant).first()
        if profile is None:
            ctx.defer(
                domain="premises_profile", stage=self.id,
                reason=(
                    "PharmacyProfile is created during tenant onboarding, not by this "
                    "engine, and the demo tenant has none. Creating one here would "
                    "bypass onboarding and fabricate a premises licence."
                ),
                required_service="PharmacyOnboardingService (tenant onboarding)",
            )
            return

        ctx.defer(
            domain="per_site_premises_state", stage=self.id,
            reason=(
                "PharmacyProfile is OneToOne with Tenant, so a per-branch premises state "
                "(CBD verified, Westlands renewal-due, warehouse pending) is not "
                "representable. One tenant carries one premises licence."
            ),
            required_service="per-site premises model (does not exist)",
        )

        reference = f"{REF}-PREMISES-TENANT"
        ctx.own(profile, domain="premises", stage=self.id, story_id=STORY_REGULATORY,
                reference=reference, purpose="Tenant premises regulatory master record.",
                reset_eligible=False)
        ctx.add_count("premises_profiles", 1)

        # Requester and reviewer must differ; the service enforces it, and the
        # scenario has to demonstrate that rather than work around it.
        requester = ctx.get("user:quality")
        reviewer = ctx.get("user:admin")
        request = verification_service.submit_verification_request(
            tenant_id=ctx.tenant.id,
            pharmacy_profile=profile,
            submitted_by=requester,
            evidence_payload={
                "truth_label": syn.TRUTH_MANUAL,
                "external_connectivity": syn.TRUTH_NOT_CONNECTED,
                "basis": "Internal document review for the demonstration scenario.",
                "synthetic": True,
            },
        )
        ctx.own(request, domain="premises_verification", stage=self.id,
                story_id=STORY_REGULATORY, reference=f"{reference}-REQ",
                purpose="Manually verified premises evidence (no regulator contacted).",
                reset_eligible=False)
        ctx.add_count("premises_verification_requests", 1)

        approved = verification_service.approve_verification_request(
            request=request,
            actor=reviewer,
            reviewer_notes="Approved on internal document review for the demonstration scenario.",
            verifier_declaration=syn.TRUTH_MANUAL,
        )
        ctx.add_count("premises_verifications_approved", 1)

        for snapshot in approved.snapshots.all().order_by("pk"):
            ctx.own(snapshot, domain="premises_snapshots", stage=self.id,
                    story_id=STORY_REGULATORY,
                    reference=f"{reference}-SNAP-{snapshot.pk}",
                    purpose="Immutable premises verification evidence.",
                    reset_eligible=False)
            ctx.add_count("premises_snapshots", 1)


# ---------------------------------------------------------------------------
# L. Summary
# ---------------------------------------------------------------------------


class StageLSummary(Stage):
    id = "L"
    label = "Master-data summary and validation"
    requires = ("A",)

    def run(self, ctx):
        ctx.add_count("stages_completed", len(ctx.completed_stages()))


STAGES: tuple[Stage, ...] = (
    StageATenant(), StageBOrganization(), StageCLocations(), StageDIdentity(),
    StageEPractitioners(), StageFPatients(), StageGManufacturers(), StageHSuppliers(),
    StageIInsurers(), StageJPricing(), StageKPremises(), StageLSummary(),
)

STAGES_BY_ID = {stage.id: stage for stage in STAGES}
STAGE_ORDER = tuple(stage.id for stage in STAGES)
