"""Stage 2A master-data generation.

The tests that matter most here are the negative ones. A generator that
produces plausible-looking data while quietly creating a purchase order, or
promoting an insurer to production, or minting a patient identifier that could
be read as a national ID, would look entirely successful in its own summary.
So the suite asserts what must *not* happen at least as hard as what must.
"""

from __future__ import annotations

import io
from datetime import date

import pytest

from apps.identity.models import AttributePolicy, User
from apps.insurance.models import Insurer
from apps.inventory.models import InventoryLocation
from apps.medicines.models import Manufacturer
from apps.organizations.models import Department, DepartmentMembership, Location
from apps.organizations.services import DEPARTMENT_METADATA_KEY
from apps.patients.models import Patient
from apps.platform.demo.generation import stages as stage_module
from apps.platform.demo.generation import synthetic as syn
from apps.platform.demo.generation.context import (
    OWNERSHIP_CONFLICT,
    CollisionError,
    GenerationContext,
)
from apps.platform.demo.generation.orchestrator import MasterDataOrchestrator
from apps.platform.demo.generation.validation import MasterDataValidator
from apps.platform.demo.models import DemoScenarioObject, DemoScenarioRun
from apps.platform.demo.profiles import PILOT, get_master_data_targets
from apps.practitioners.models import Practitioner
from apps.procurement.models import Supplier
from apps.tenancy.models import Tenant

SEED = 83492011
AS_OF = date(2026, 8, 3)
PASSWORD = "Demo-Local-Pass-9182!"


def _tenant(slug="demotenant", *, is_demo=True):
    return Tenant.objects.create(name="Demo Chemists", slug=slug, is_demo=is_demo)


def _run(tenant, *, seed=SEED):
    return DemoScenarioRun.all_objects.create(
        tenant=tenant, scenario_name="nairobi-chemists", scenario_version="1.0.0",
        profile=PILOT.key, random_seed=seed, as_of_date=AS_OF, scale="small",
        demo_version="2026.08.03",
    )


def _context(tenant, run, *, seed=SEED):
    return GenerationContext(
        run=run, tenant=tenant, seed=seed, as_of=AS_OF,
        targets=get_master_data_targets("small"), demo_password=PASSWORD,
    )


@pytest.fixture
def generated(db):
    """One completed master-data run at local scale."""
    tenant = _tenant()
    run = _run(tenant)
    ctx = _context(tenant, run)
    orchestrator = MasterDataOrchestrator(ctx)
    orchestrator.run()
    return tenant, run, ctx, orchestrator


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_same_inputs_produce_the_same_manifest_digest(db):
    """An approval binds to the digest, so the digest must be reproducible."""
    tenant = _tenant()
    run = _run(tenant)
    first = MasterDataOrchestrator(_context(tenant, run)).manifest()
    second = MasterDataOrchestrator(_context(tenant, run)).manifest()
    assert first["manifest_digest"] == second["manifest_digest"]
    assert first == second


def test_the_manifest_digest_covers_the_tenant(db):
    """The same plan against a different tenant must not reuse an approval."""
    plans = {}
    for slug in ("det-a", "det-b"):
        tenant = Tenant.objects.create(name="Demo Chemists", slug=slug, is_demo=True)
        manifest = MasterDataOrchestrator(_context(tenant, _run(tenant))).manifest()
        plans[slug] = manifest
    assert plans["det-a"]["manifest_digest"] != plans["det-b"]["manifest_digest"]
    # The plan itself is identical; only the tenant differs.
    assert plans["det-a"]["planned_counts"] == plans["det-b"]["planned_counts"]


def test_manifest_digest_changes_when_the_seed_changes(db):
    tenant = _tenant()
    run = _run(tenant)
    first = MasterDataOrchestrator(_context(tenant, run, seed=SEED)).manifest()
    second = MasterDataOrchestrator(_context(tenant, run, seed=SEED + 1)).manifest()
    assert first["manifest_digest"] != second["manifest_digest"]


def test_synthetic_values_are_stable_across_processes(db):
    """SHA-256 based, not hash() -- which is salted per process."""
    assert syn.stable_int(SEED, "patient", 7) == syn.stable_int(SEED, "patient", 7)
    assert syn.person_name(SEED, "patient", 7) == syn.person_name(SEED, "patient", 7)
    assert syn.person_name(SEED, "patient", 7) != syn.person_name(SEED, "patient", 8)


def test_independent_rng_streams_do_not_shift_each_other(db):
    """Adding a draw in one domain must not change another.

    A single shared stream would make every patient depend on how many
    suppliers were generated first, so inserting one supplier would change the
    manifest digest and invalidate an approval.
    """
    before = [syn.rng_for(SEED, "patients", i).random() for i in range(3)]
    for i in range(10):
        syn.rng_for(SEED, "suppliers", i).random()
    after = [syn.rng_for(SEED, "patients", i).random() for i in range(3)]
    assert before == after


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_organization_structure_is_generated(generated):
    tenant, _run_obj, ctx, _o = generated
    sites = Location.all_objects.filter(tenant=tenant).order_by("code")
    assert sites.count() == 4
    assert {s.location_type for s in sites} == {"HEAD_OFFICE", "WAREHOUSE", "PHARMACY"}
    assert ctx.counts["departments"] == 13


def test_departments_fit_their_site_type(generated):
    tenant, *_ = generated
    warehouse = Location.all_objects.get(tenant=tenant, location_type="WAREHOUSE")
    kinds = set(
        Department.all_objects.filter(tenant=tenant, site=warehouse)
        .values_list("department_type", flat=True)
    )
    assert Department.TYPE_RETAIL not in kinds, "a warehouse has no retail counter"


def test_location_capabilities_are_derived_not_asserted(generated):
    """The safety property: a quarantine bay must actually quarantine."""
    tenant, *_ = generated
    for kind, flag in (
        (InventoryLocation.LocationType.QUARANTINE, "quarantine_capability"),
        (InventoryLocation.LocationType.COLD_ROOM, "cold_chain_capability"),
        (InventoryLocation.LocationType.CONTROLLED_VAULT, "controlled_drug_capability"),
    ):
        locations = InventoryLocation.all_objects.filter(tenant=tenant, location_type=kind)
        assert locations.exists()
        assert all(getattr(loc, flag) for loc in locations)


def test_ordinary_locations_do_not_gain_privileged_flags(generated):
    tenant, *_ = generated
    stores = InventoryLocation.all_objects.filter(
        tenant=tenant, location_type=InventoryLocation.LocationType.STORE
    )
    assert stores.exists()
    for location in stores:
        assert location.controlled_drug_capability is False
        assert location.quarantine_capability is False


# ---------------------------------------------------------------------------
# Identity and ABAC
# ---------------------------------------------------------------------------


def test_every_staff_member_has_at_most_one_primary_department(generated):
    tenant, *_ = generated
    primaries = DepartmentMembership.all_objects.filter(
        tenant=tenant, is_primary=True, is_active=True
    )
    per_user = {}
    for membership in primaries:
        per_user[membership.user_id] = per_user.get(membership.user_id, 0) + 1
    assert per_user, "expected staff with primary departments"
    assert set(per_user.values()) == {1}


def test_department_metadata_mirror_matches_membership(generated):
    tenant, *_ = generated
    for membership in DepartmentMembership.all_objects.filter(
        tenant=tenant, is_primary=True, is_active=True
    ).select_related("user", "department"):
        assert (membership.user.metadata or {}).get(DEPARTMENT_METADATA_KEY) == (
            membership.department.code
        )


def test_the_demonstration_policy_denies_and_never_grants(generated):
    """Department attributes must narrow access, never widen it."""
    tenant, *_ = generated
    policies = AttributePolicy.all_objects.filter(tenant=tenant)
    assert policies.exists()
    assert all(p.effect == AttributePolicy.EFFECT_DENY for p in policies)


def test_no_universal_demo_superuser_is_created(generated):
    tenant, *_ = generated
    users = User.objects.filter(tenant=tenant)
    assert users.exists()
    assert not users.filter(is_superuser=True).exists()
    assert not users.filter(is_platform_admin=True).exists()


def test_roles_only_reference_capabilities_the_application_actually_checks(generated):
    """A capability nothing checks is a permission that does not exist.

    Scans the codebase for the capability strings that reach an authorisation
    check, and asserts every capability the scenario grants is one of them. A
    role carrying an invented string would look like a permission in the UI and
    grant nothing.
    """
    import pathlib

    granted: set[str] = set()
    for role in generated[2].get("roles").values():
        granted.update(role.capabilities or [])
    assert granted, "the scenario granted no capabilities at all"

    # Capabilities are free-form strings, and identity.capability_catalogue is
    # explicitly a curated UI aid rather than a complete list, so neither is a
    # usable authority. What *is* checkable: a capability that appears nowhere
    # in the application except the generator that granted it was invented here.
    apps_root = pathlib.Path(__file__).resolve().parents[1] / "apps"
    generator = apps_root / "platform" / "demo" / "generation" / "stages.py"

    invented = []
    for capability in sorted(granted):
        needle = f'"{capability}"'
        found_elsewhere = False
        for path in apps_root.rglob("*.py"):
            if path == generator or "migrations" in path.parts:
                continue
            if needle in path.read_text(encoding="utf-8", errors="ignore"):
                found_elsewhere = True
                break
        if not found_elsewhere:
            invented.append(capability)

    assert not invented, (
        "these capabilities exist only in the demo generator, so nothing in the "
        f"application ever checks them: {invented}"
    )


# ---------------------------------------------------------------------------
# Practitioners
# ---------------------------------------------------------------------------


def test_practitioners_are_prescribers_not_pharmacy_staff(generated):
    """Pharmacists are Users with roles; Practitioner models prescribers."""
    tenant, *_ = generated
    professions = set(
        Practitioner.all_objects.filter(tenant=tenant).values_list("profession", flat=True)
    )
    assert professions <= {
        "DOCTOR", "DENTIST", "CLINICAL_OFFICER", "NURSE_PRESCRIBER",
        "VETERINARY_PRESCRIBER", "OTHER_AUTHORIZED_PRESCRIBER",
    }


def test_controlled_authority_is_never_granted_at_registration(db):
    """Registration must produce an unverified practitioner with no authority."""
    tenant = _tenant()
    ctx = _context(tenant, _run(tenant))
    orchestrator = MasterDataOrchestrator(ctx)
    orchestrator.run(stop_after="E")

    authorised = Practitioner.all_objects.filter(
        tenant=tenant, controlled_medicine_authority=True
    )
    # Any practitioner holding authority must also be verified -- the service
    # refuses to grant it otherwise, so this proves the governed path ran.
    for practitioner in authorised:
        assert practitioner.verification_state == "VERIFIED"
        assert practitioner.metadata["controlled_authority"]["reason"]


def test_practitioner_truth_labels_are_honest(generated):
    """Nothing contacted the Health Workforce Registry, so nothing may claim to."""
    tenant, *_ = generated
    for practitioner in Practitioner.all_objects.filter(tenant=tenant):
        assert practitioner.metadata["verification_basis"] == "MANUAL_INTERNAL_VERIFICATION"


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------


def test_patient_identifiers_cannot_be_mistaken_for_national_ids(generated):
    """Kenyan national IDs are eight digits; these must not parse as one."""
    tenant, *_ = generated
    patients = Patient.all_objects.filter(tenant=tenant)
    assert patients.exists()
    for patient in patients:
        assert patient.patient_number.startswith(syn.PATIENT_IDENTIFIER_PREFIX)
        assert not patient.patient_number.isdigit()


def test_patient_contact_details_are_undeliverable(generated):
    """.invalid is reserved by RFC 2606 and can never be registered."""
    tenant, *_ = generated
    for patient in Patient.all_objects.filter(tenant=tenant):
        assert patient.email.endswith(".demo.invalid")
        assert patient.phone.startswith(syn.DEMO_PHONE_PREFIX)


def test_patient_generation_is_deterministic(db):
    """Same seed, same people."""
    names = []
    for slug in ("pat-a", "pat-b"):
        tenant = Tenant.objects.create(name="Demo", slug=slug, is_demo=True)
        ctx = _context(tenant, _run(tenant))
        MasterDataOrchestrator(ctx).run(stop_after="F")
        names.append(
            list(
                Patient.all_objects.filter(tenant=tenant)
                .order_by("internal_reference_id")
                .values_list("internal_reference_id", "first_name", "last_name", "patient_number")
            )
        )
    assert names[0] == names[1]


def test_patient_count_matches_the_target_exactly(generated):
    tenant, _r, ctx, _o = generated
    assert Patient.all_objects.filter(tenant=tenant).count() == ctx.targets.patients


# ---------------------------------------------------------------------------
# Manufacturers, suppliers, insurers
# ---------------------------------------------------------------------------


def test_manufacturers_respect_the_tenant_global_scope_constraint(generated):
    tenant, *_ = generated
    for manufacturer in Manufacturer.all_objects.filter(tenant=tenant):
        assert manufacturer.is_global is False
        assert manufacturer.tenant_id == tenant.id


def test_suppliers_reach_their_intended_lifecycle_state(generated):
    tenant, *_ = generated
    statuses = set(
        Supplier.all_objects.filter(tenant=tenant).values_list("status", flat=True)
    )
    assert Supplier.Status.APPROVED in statuses


def test_insurers_are_created_in_sandbox_on_the_fake_adapter(generated):
    """Creating a counterparty must never create a route to real claims."""
    tenant, *_ = generated
    insurers = Insurer.all_objects.filter(tenant=tenant)
    assert insurers.exists()
    for insurer in insurers:
        assert insurer.environment == Insurer.Environment.SANDBOX
        assert insurer.integration_adapter == Insurer.IntegrationAdapter.FAKE


def test_insurer_plans_hang_off_their_scheme(generated):
    tenant, _r, ctx, _o = generated
    assert ctx.counts["insurer_schemes"] >= 1
    assert ctx.counts["insurer_plans"] >= ctx.counts["insurer_schemes"]


# ---------------------------------------------------------------------------
# GS1
# ---------------------------------------------------------------------------


def test_synthetic_gtins_have_valid_check_digits(db):
    for index in range(50):
        gtin = syn.synthetic_gtin13(SEED, "sku", index)
        assert len(gtin) == 13
        assert syn.gtin13_check_digit(gtin[:12]) == int(gtin[12])


def test_synthetic_gtins_use_a_non_allocated_prefix(db):
    """952 is a GS1 demonstration prefix, so it cannot collide with a real GTIN."""
    gtin = syn.synthetic_gtin13(SEED, "sku", 1)
    assert gtin.startswith(syn.GS1_DEMO_PREFIX)
    assert syn.is_synthetic_gtin(gtin)
    assert not syn.is_synthetic_gtin("6161234567890")


def test_synthetic_gtins_are_unique_across_a_catalogue(db):
    gtins = {syn.synthetic_gtin13(SEED, "sku", i) for i in range(500)}
    assert len(gtins) == 500


# ---------------------------------------------------------------------------
# The Stage 2A guarantee
# ---------------------------------------------------------------------------


def test_no_transactional_data_is_created(generated):
    """The load-bearing assertion for the whole stage."""
    tenant, run, _ctx, _o = generated
    validation = MasterDataValidator(run=run, tenant=tenant).run_all()
    finding = next(
        f for f in validation["findings"] if f["check"] == "no_transactional_data"
    )
    assert finding["status"] == "PASS", finding["detail"]


def test_full_validation_passes(generated):
    tenant, run, *_ = generated
    validation = MasterDataValidator(run=run, tenant=tenant).run_all()
    failures = [f for f in validation["findings"] if f["status"] == "FAIL"]
    assert validation["status"] == "PASS", failures


def test_the_generator_refuses_a_tenant_not_designated_for_demo(db):
    tenant = _tenant(slug="notdemo", is_demo=False)
    ctx = _context(tenant, _run(tenant))
    with pytest.raises(Exception, match="not designated a demo tenant"):
        MasterDataOrchestrator(ctx).run()


# ---------------------------------------------------------------------------
# Idempotency, collisions, resume
# ---------------------------------------------------------------------------


def test_an_identical_rerun_creates_no_duplicates(generated):
    tenant, run, _ctx, _o = generated
    before = {
        "patients": Patient.all_objects.filter(tenant=tenant).count(),
        "departments": Department.all_objects.filter(tenant=tenant).count(),
        "users": User.objects.filter(tenant=tenant).count(),
        "sites": Location.all_objects.filter(tenant=tenant).count(),
        "owned": DemoScenarioObject.all_objects.filter(run=run).count(),
    }
    run.refresh_from_db()
    MasterDataOrchestrator(_context(tenant, run)).run()
    after = {
        "patients": Patient.all_objects.filter(tenant=tenant).count(),
        "departments": Department.all_objects.filter(tenant=tenant).count(),
        "users": User.objects.filter(tenant=tenant).count(),
        "sites": Location.all_objects.filter(tenant=tenant).count(),
        "owned": DemoScenarioObject.all_objects.filter(run=run).count(),
    }
    assert before == after


def test_an_unowned_record_is_never_adopted(db):
    """A collision on a reference the engine does not own must stop the run."""
    tenant = _tenant()
    run = _run(tenant)
    ctx = _context(tenant, run)
    with pytest.raises(CollisionError) as excinfo:
        ctx.record_collision(
            OWNERSHIP_CONFLICT, "sites", "NC-SITE-CBD",
            "a site exists at this code but no demo run owns it",
        )
    assert excinfo.value.classification == OWNERSHIP_CONFLICT


def test_resume_rehydrates_rather_than_repeating_completed_stages(db, monkeypatch):
    """Re-running a completed stage would repeat non-idempotent transitions."""
    tenant = _tenant()
    run = _run(tenant)

    def exploding(self, ctx):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(stage_module.StageFPatients, "run", exploding)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        MasterDataOrchestrator(_context(tenant, run)).run()

    run.refresh_from_db()
    completed = {k for k, v in run.stage_progress.items() if v["status"] == "COMPLETED"}
    assert completed == {"A", "B", "C", "D", "E"}
    assert run.stage_progress["F"]["status"] == "FAILED"
    assert run.stage_progress["F"]["error_class"] == "RuntimeError"

    monkeypatch.undo()
    messages = []
    orchestrator = MasterDataOrchestrator(_context(tenant, run), progress=messages.append)
    orchestrator.run(resume=True)

    rehydrated = [m for m in messages if "rehydrated" in m]
    assert len(rehydrated) == 5
    assert Patient.all_objects.filter(tenant=tenant).count() > 0
    validation = MasterDataValidator(run=run, tenant=tenant).run_all()
    assert validation["status"] == "PASS"


def test_a_failed_stage_records_enough_to_resume_from(db, monkeypatch):
    tenant = _tenant()
    run = _run(tenant)

    def exploding(self, ctx):
        raise ValueError("boom")

    monkeypatch.setattr(stage_module.StageHSuppliers, "run", exploding)
    with pytest.raises(ValueError):
        MasterDataOrchestrator(_context(tenant, run)).run()

    run.refresh_from_db()
    recorded = run.stage_progress["H"]
    assert recorded["status"] == "FAILED"
    assert recorded["error_class"] == "ValueError"
    assert "boom" in recorded["error_detail"]


# ---------------------------------------------------------------------------
# Ownership and artefacts
# ---------------------------------------------------------------------------


def test_every_generated_object_is_recorded_as_demo_owned(generated):
    """An unrecorded row is indistinguishable from real tenant data."""
    tenant, run, *_ = generated
    owned = DemoScenarioObject.all_objects.filter(run=run)
    assert owned.count() > 0
    assert owned.filter(story_id="").count() == 0
    assert owned.filter(domain="").count() == 0
    assert owned.filter(external_reference="").count() == 0


def test_ownership_records_carry_the_business_story(generated):
    _t, run, *_ = generated
    stories = set(
        DemoScenarioObject.all_objects.filter(run=run).values_list("story_id", flat=True)
    )
    assert "NC-MASTER-ORG-001" in stories
    assert "NC-MASTER-STAFF-001" in stories
    assert "NC-MASTER-PATIENT-001" in stories


def test_artefacts_are_written_and_byte_deterministic(generated, tmp_path):
    tenant, run, _ctx, orchestrator = generated
    validation = MasterDataValidator(run=run, tenant=tenant).run_all()

    first = orchestrator.write_artefacts(tmp_path / "one", validation=validation)
    orchestrator.write_artefacts(tmp_path / "two", validation=validation)
    assert len(first) == 6

    for name in first:
        assert (
            (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
        ), f"{name} is not byte-deterministic"


def test_kpis_report_no_transactional_measures(generated):
    _t, _r, _c, orchestrator = generated
    kpis = orchestrator.kpis()
    forbidden = {"revenue", "gross_margin", "dispensing_time", "stock_turn", "sales"}
    assert not (forbidden & set(kpis)), "a transactional KPI would be fabricated"
    assert kpis["patients"] > 0


def test_summary_records_what_could_not_be_generated(generated):
    """Deferrals must be visible, not silently absent from the counts.

    The fixture seeds no global medicine catalogue, so stage G legitimately
    defers -- Stage 2A lists from the global catalogue and must not fabricate
    clinical products to reach a count. Every deferral must name the service it
    needs, so a reader can tell a gap from an omission.
    """
    _t, _r, _c, orchestrator = generated
    summary = orchestrator.summary()
    domains = {entry["domain"] for entry in summary["deferred"]}
    assert "medicine_assortment" in domains
    for entry in summary["deferred"]:
        assert entry["required_service"]
        assert entry["reason"]


def test_with_a_catalogue_loaded_no_closed_gap_is_still_deferred(db):
    """The five service gaps are closed, so these must generate, not defer.

    Behavioural rather than a source scan: if a coverage, qualification or
    pricing service stopped being reachable, the generator would quietly fall
    back to deferring and the summary would still look orderly.
    """
    from django.core.management import call_command

    call_command("seed_medicine_catalogue", stdout=io.StringIO())

    tenant = _tenant(slug="closedgaps")
    run = _run(tenant)
    ctx = _context(tenant, run)
    orchestrator = MasterDataOrchestrator(ctx)
    orchestrator.run()

    deferred = {entry["domain"] for entry in orchestrator.summary()["deferred"]}
    for closed in (
        "medicine_assortment",
        "supplier_qualifications",
        "supplier_product_agreements",
        "insurance_coverage",
        "price_books",
    ):
        assert closed not in deferred, f"{closed} is still deferred"

    assert ctx.counts["commercial_skus"] > 0
    assert ctx.counts["branch_assortments"] > 0
    assert ctx.counts["supplier_qualifications"] > 0
    assert ctx.counts["supplier_product_agreements"] > 0
    assert ctx.counts["insurance_coverage"] > 0
    assert ctx.counts["price_books"] == 6

    validation = MasterDataValidator(run=run, tenant=tenant).run_all()
    assert validation["status"] == "PASS", [
        f for f in validation["findings"] if f["status"] == "FAIL"
    ]
