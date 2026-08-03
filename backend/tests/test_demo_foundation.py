"""Stage 1 demo foundation: gates, ownership, classification, manifest.

The engine writes fabricated trading history into a real tenant, so these tests
are about refusal far more than about capability. Each one pins a way the
foundation must say no.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.identity.models import User
from apps.platform.demo import safety
from apps.platform.demo.classification import (
    DEMO_DATA_PRESENT,
    EMPTY_SAFE_TO_SEED,
    REAL_DATA_PRESENT,
    classify_tenant,
)
from apps.platform.demo.manifest import build_manifest, digest_manifest, finalise
from apps.platform.demo.models import DemoScenarioRun, DemoSeedApproval
from apps.platform.demo.profiles import PILOT, SCENARIO_VERSION, get_profile
from apps.tenancy.models import Tenant

AS_OF = date(2026, 8, 2)
SEED = 20260802


@pytest.fixture
def demo_tenant(db):
    return Tenant.objects.create(
        name="Demo Tenant", slug="demo-tenant", status=Tenant.STATUS_ACTIVE, is_demo=True
    )


@pytest.fixture
def plain_tenant(db):
    return Tenant.objects.create(
        name="Real Tenant", slug="real-tenant", status=Tenant.STATUS_ACTIVE
    )


@pytest.fixture
def users(db, demo_tenant):
    requester = User.objects.create(username="demo_requester", tenant=demo_tenant)
    approver = User.objects.create(username="demo_approver", tenant=demo_tenant)
    return requester, approver


# --------------------------------------------------------------------------
# Tenant designation
# --------------------------------------------------------------------------


def test_is_demo_defaults_false(plain_tenant):
    """A tenant is never a demo tenant by accident."""
    assert plain_tenant.is_demo is False


def test_designation_requires_matching_name(db, plain_tenant):
    User.objects.create(username="po", is_superuser=True, tenant=plain_tenant)
    with pytest.raises(CommandError, match="does not match"):
        call_command(
            "designate_demo_tenant",
            tenant_id=str(plain_tenant.id),
            tenant_slug=plain_tenant.slug,
            tenant_name="Wrong Name",
            reason="test",
            actor_username="po",
            confirm=plain_tenant.slug,
        )
    plain_tenant.refresh_from_db()
    assert plain_tenant.is_demo is False


def test_designation_requires_confirm_to_repeat_slug(db, plain_tenant):
    User.objects.create(username="po2", is_superuser=True, tenant=plain_tenant)
    with pytest.raises(CommandError, match="confirm"):
        call_command(
            "designate_demo_tenant",
            tenant_id=str(plain_tenant.id),
            tenant_slug=plain_tenant.slug,
            tenant_name=plain_tenant.name,
            reason="test",
            actor_username="po2",
            confirm="something-else",
        )


def test_designation_requires_platform_owner(db, plain_tenant):
    User.objects.create(username="ordinary", tenant=plain_tenant)
    with pytest.raises(CommandError, match="Platform Owner"):
        call_command(
            "designate_demo_tenant",
            tenant_id=str(plain_tenant.id),
            tenant_slug=plain_tenant.slug,
            tenant_name=plain_tenant.name,
            reason="test",
            actor_username="ordinary",
            confirm=plain_tenant.slug,
        )


def test_designation_succeeds_and_audits(db, plain_tenant):
    from apps.audit.models import AuditEvent

    User.objects.create(username="po3", is_superuser=True, tenant=plain_tenant)
    call_command(
        "designate_demo_tenant",
        tenant_id=str(plain_tenant.id),
        tenant_slug=plain_tenant.slug,
        tenant_name=plain_tenant.name,
        reason="authorised demonstration tenant",
        actor_username="po3",
        confirm=plain_tenant.slug,
    )
    plain_tenant.refresh_from_db()
    assert plain_tenant.is_demo is True
    assert AuditEvent.all_objects.filter(
        tenant=plain_tenant, action="DEMO_TENANT_DESIGNATED"
    ).exists()


# --------------------------------------------------------------------------
# Safety gates
# --------------------------------------------------------------------------


def test_non_demo_tenant_is_refused(db, plain_tenant, settings):
    settings.DAWATRACE_ENV = "development"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    result = safety.evaluate_all(tenant=plain_tenant, allow_demo_seed=True)
    assert not result.ok
    assert any("designated a demo tenant" in f for f in result.failed)


def test_wrong_slug_is_refused(db, demo_tenant, settings):
    settings.DAWATRACE_ENV = "development"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    result = safety.evaluate_all(
        tenant=demo_tenant, allow_demo_seed=True, confirm_slug="not-this-one"
    )
    assert not result.ok
    assert any("confirm-tenant-slug" in f for f in result.failed)


def test_wrong_tenant_id_is_refused(db, demo_tenant, settings):
    settings.DAWATRACE_ENV = "development"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    result = safety.evaluate_all(
        tenant=demo_tenant,
        allow_demo_seed=True,
        confirm_id="00000000-0000-0000-0000-000000000000",
    )
    assert not result.ok
    assert any("confirm-tenant-id" in f for f in result.failed)


def test_wrong_name_is_refused(db, demo_tenant, settings):
    settings.DAWATRACE_ENV = "development"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    result = safety.evaluate_all(
        tenant=demo_tenant, allow_demo_seed=True, confirm_name="Some Other Pharmacy"
    )
    assert not result.ok
    assert any("confirm-tenant-name" in f for f in result.failed)


@pytest.mark.parametrize("env", ["production", "prod", "live"])
def test_allow_demo_seed_alone_never_permits_production(db, demo_tenant, settings, env):
    """The generic flag must not be a production key."""
    settings.DAWATRACE_ENV = env
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    result = safety.evaluate_all(
        tenant=demo_tenant, allow_demo_seed=True, allow_production_demo_seed=False
    )
    assert not result.ok
    assert any("--allow-production-demo-seed" in f for f in result.failed)


def test_production_override_still_fails_without_approval(db, demo_tenant, settings):
    settings.DAWATRACE_ENV = "production"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    result = safety.evaluate_all(
        tenant=demo_tenant,
        allow_demo_seed=True,
        allow_production_demo_seed=True,
        backup_present=True,
        capacity_ok=True,
        data_classification=EMPTY_SAFE_TO_SEED,
    )
    assert not result.ok
    assert any("approval" in f.lower() for f in result.failed)


def test_expired_approval_fails(db, demo_tenant, users, settings):
    settings.DAWATRACE_ENV = "production"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    requester, approver = users
    approval = DemoSeedApproval.all_objects.create(
        tenant=demo_tenant, requested_by=requester, approved_by=approver,
        request_reason="demo", profile=PILOT.key, scenario_version=SCENARIO_VERSION,
        random_seed=SEED, as_of_date=AS_OF, manifest_digest="abc",
        status=DemoSeedApproval.Status.APPROVED,
        approved_at=timezone.now() - timedelta(hours=9),
        expires_at=timezone.now() - timedelta(hours=1),
    )
    usable, why = approval.is_usable(now=timezone.now(), manifest_digest="abc")
    assert not usable and "expired" in why


def test_requester_cannot_approve_own_request(db, demo_tenant, users):
    requester, _ = users
    with pytest.raises(ValidationError, match="cannot approve"):
        DemoSeedApproval.all_objects.create(
            tenant=demo_tenant, requested_by=requester, approved_by=requester,
            request_reason="self approval", profile=PILOT.key,
            scenario_version=SCENARIO_VERSION, random_seed=SEED, as_of_date=AS_OF,
            manifest_digest="abc", expires_at=timezone.now() + timedelta(hours=1),
        )


def test_changed_manifest_invalidates_approval(db, demo_tenant, users):
    requester, approver = users
    approval = DemoSeedApproval.all_objects.create(
        tenant=demo_tenant, requested_by=requester, approved_by=approver,
        request_reason="demo", profile=PILOT.key, scenario_version=SCENARIO_VERSION,
        random_seed=SEED, as_of_date=AS_OF, manifest_digest="approved-digest",
        status=DemoSeedApproval.Status.APPROVED, approved_at=timezone.now(),
        expires_at=timezone.now() + timedelta(hours=4),
    )
    ok, _ = approval.is_usable(now=timezone.now(), manifest_digest="approved-digest")
    assert ok
    changed, why = approval.is_usable(now=timezone.now(), manifest_digest="different-digest")
    assert not changed and "digest" in why


def test_live_provider_credentials_block(db, settings):
    settings.DAWATRACE_PPB_API_KEY = "a-real-looking-key"
    result = safety.check_provider_credentials()
    assert not result.ok
    assert any("PPB" in f for f in result.failed)


def test_enabled_notifications_block(db, settings):
    settings.DAWATRACE_NOTIFICATIONS_ENABLED = True
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    result = safety.check_external_side_effects()
    assert not result.ok
    assert any("notification" in f for f in result.failed)


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def _manifest_for(tenant, seed=SEED, as_of=AS_OF):
    return finalise(
        build_manifest(
            tenant=tenant, profile=PILOT, random_seed=seed, as_of_date=as_of,
            environment="test", existing_counts={"patients": 0},
            data_classification=EMPTY_SAFE_TO_SEED,
        )
    )


def test_identical_plans_produce_identical_digests(db, demo_tenant):
    assert _manifest_for(demo_tenant)["manifest_sha256"] == _manifest_for(demo_tenant)["manifest_sha256"]


def test_changed_seed_changes_digest(db, demo_tenant):
    a = _manifest_for(demo_tenant, seed=1)
    b = _manifest_for(demo_tenant, seed=2)
    assert a["manifest_sha256"] != b["manifest_sha256"]


def test_changed_as_of_date_changes_digest(db, demo_tenant):
    a = _manifest_for(demo_tenant, as_of=date(2026, 8, 2))
    b = _manifest_for(demo_tenant, as_of=date(2026, 8, 3))
    assert a["manifest_sha256"] != b["manifest_sha256"]


def test_digest_is_order_independent(db, demo_tenant):
    """Key order must not change the digest, or reruns would spuriously differ."""
    m = _manifest_for(demo_tenant)
    body = {k: v for k, v in m.items() if k != "manifest_sha256"}
    reordered = dict(reversed(list(body.items())))
    assert digest_manifest(body) == digest_manifest(reordered)


def test_manifest_records_finance_exclusions(db, demo_tenant):
    m = _manifest_for(demo_tenant)
    for excluded in ("general_ledger", "trial_balance", "vat_return", "ar_ageing"):
        assert excluded in m["excluded_domains"]


# --------------------------------------------------------------------------
# Profile bounds
# --------------------------------------------------------------------------


def test_pilot_profile_counts_remain_bounded():
    """The pilot exists to measure runtime, not to move volume."""
    c = PILOT.counts
    assert c["branches"] == 2
    assert c["patients"] <= 500
    assert c["inventory_ledger_entries"] <= 5000
    assert c["sales_dispensing_events"] <= 2000
    assert c["prescriptions"] <= 500
    assert c["claims"] <= 100
    assert PILOT.planned_total() < 10_000


def test_unknown_profile_is_rejected():
    with pytest.raises(KeyError, match="Unknown demo profile"):
        get_profile("regional-chain")


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def test_empty_tenant_is_safe_to_seed(db, demo_tenant):
    assert classify_tenant(demo_tenant).verdict == EMPTY_SAFE_TO_SEED


def test_transactional_records_classify_as_real_data(db, demo_tenant):
    """Low row counts must not be mistaken for an empty tenant."""
    report = classify_tenant(demo_tenant)
    assert report.verdict == EMPTY_SAFE_TO_SEED

    from apps.patients.models import Patient

    Patient.all_objects.create(tenant=demo_tenant, internal_reference_id="DEMO-REAL-1")
    after = classify_tenant(demo_tenant)
    assert after.verdict in {REAL_DATA_PRESENT, "UNCLASSIFIED_DATA_PRESENT"}
    assert after.verdict != EMPTY_SAFE_TO_SEED


def test_demo_owned_records_classify_as_demo_data(db, demo_tenant):
    from django.contrib.contenttypes.models import ContentType

    from apps.patients.models import Patient
    from apps.platform.demo.models import DemoScenarioObject

    run = DemoScenarioRun.all_objects.create(
        tenant=demo_tenant, scenario_name="nairobi-chemists", scenario_version=SCENARIO_VERSION,
        profile=PILOT.key, random_seed=SEED, as_of_date=AS_OF,
    )
    patient = Patient.all_objects.create(tenant=demo_tenant, internal_reference_id="DEMO-OWNED-1")
    DemoScenarioObject.all_objects.create(
        run=run, tenant=demo_tenant,
        content_type=ContentType.objects.get_for_model(Patient),
        object_id=str(patient.pk), generator="patients", seed_key="p-1",
    )
    assert classify_tenant(demo_tenant).verdict == DEMO_DATA_PRESENT


# --------------------------------------------------------------------------
# Run lifecycle
# --------------------------------------------------------------------------


def test_run_state_machine_rejects_illegal_transitions(db, demo_tenant):
    run = DemoScenarioRun.all_objects.create(
        tenant=demo_tenant, scenario_name="nairobi-chemists", scenario_version=SCENARIO_VERSION,
        profile=PILOT.key, random_seed=SEED, as_of_date=AS_OF,
    )
    with pytest.raises(ValidationError, match="cannot move"):
        run.transition_to(DemoScenarioRun.State.COMPLETED)
    run.transition_to(DemoScenarioRun.State.DRY_RUN_COMPLETE)
    assert run.state == DemoScenarioRun.State.DRY_RUN_COMPLETE


def test_archived_is_terminal(db, demo_tenant):
    run = DemoScenarioRun.all_objects.create(
        tenant=demo_tenant, scenario_name="nairobi-chemists", scenario_version=SCENARIO_VERSION,
        profile=PILOT.key, random_seed=SEED, as_of_date=AS_OF,
        state=DemoScenarioRun.State.ARCHIVED,
    )
    with pytest.raises(ValidationError, match="terminal"):
        run.transition_to(DemoScenarioRun.State.RUNNING)


def test_rerunning_same_plan_reuses_the_run(db, demo_tenant, settings, tmp_path):
    """Idempotency anchor: same plan must not create a second run."""
    settings.DAWATRACE_ENV = "development"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    settings.DAWATRACE_NOTIFICATIONS_ENABLED = False

    args = dict(
        tenant_slug=demo_tenant.slug, profile=PILOT.key, random_seed=SEED,
        as_of_date=AS_OF.isoformat(), dry_run=True, allow_demo_seed=True,
        output_manifest=str(tmp_path / "m.json"),
    )
    call_command("seed_demo_scenario", **args)
    call_command("seed_demo_scenario", **args)
    # all_objects: the default manager is tenant-scoped and a test has no
    # tenant context set.
    assert DemoScenarioRun.all_objects.filter(tenant=demo_tenant).count() == 1


def test_a_run_without_a_stage_refuses_rather_than_doing_nothing(db, demo_tenant, settings):
    """A real run must fail loudly rather than leave an empty tenant.

    Stage 2A added --stage=master-data. Omitting it still refuses, because a
    command that silently planned and exited would leave an empty tenant
    looking like a successful seed -- the failure this guard exists for.
    """
    settings.DAWATRACE_ENV = "development"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    settings.DAWATRACE_NOTIFICATIONS_ENABLED = False
    with pytest.raises(CommandError, match="Stage 2B"):
        call_command(
            "seed_demo_scenario", tenant_slug=demo_tenant.slug, profile=PILOT.key,
            random_seed=SEED, as_of_date=AS_OF.isoformat(), allow_demo_seed=True,
        )


def test_master_data_stage_refuses_a_digest_that_does_not_match_the_plan(
    db, demo_tenant, settings
):
    """An approval authorises one exact plan, so a stale digest must not run."""
    settings.DAWATRACE_ENV = "development"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    settings.DAWATRACE_NOTIFICATIONS_ENABLED = False
    with pytest.raises(CommandError, match="does not match the plan"):
        call_command(
            "seed_demo_scenario", tenant_slug=demo_tenant.slug, profile=PILOT.key,
            random_seed=SEED, as_of_date=AS_OF.isoformat(), allow_demo_seed=True,
            stage="master-data", manifest_digest="0" * 64,
        )


def test_reset_is_refused_in_stage_one(db, demo_tenant, settings):
    settings.DAWATRACE_ENV = "development"
    settings.FHIR_WRITE_INTERACTIONS_ENABLED = False
    with pytest.raises(CommandError, match="Reset is not implemented"):
        call_command(
            "seed_demo_scenario", tenant_slug=demo_tenant.slug, profile=PILOT.key,
            random_seed=SEED, as_of_date=AS_OF.isoformat(), allow_demo_seed=True,
            reset_demo_data=True,
        )


def test_engine_never_creates_a_tenant(db, settings):
    settings.DAWATRACE_ENV = "development"
    with pytest.raises(CommandError, match="never creates a tenant"):
        call_command(
            "seed_demo_scenario", tenant_slug="does-not-exist", profile=PILOT.key,
            random_seed=SEED, as_of_date=AS_OF.isoformat(), allow_demo_seed=True,
        )


def test_immutable_domains_are_marked_not_reset_eligible(db, demo_tenant):
    """Archival, never deletion, for domains that forbid it."""
    from apps.platform.demo.classification import INSPECTED_MODELS

    immutable = {label for label, _a, _m, imm in INSPECTED_MODELS if imm}
    assert {"audit_events", "inventory_ledger_entries", "prescriptions"} <= immutable


def test_inspect_command_reports_json(db, demo_tenant, tmp_path, capsys):
    out = tmp_path / "report.json"
    call_command(
        "inspect_demo_tenant", tenant_slug=demo_tenant.slug,
        tenant_id=str(demo_tenant.id), output=str(out),
    )
    payload = json.loads(out.read_text())
    assert payload["tenant"]["slug"] == demo_tenant.slug
    assert payload["tenant"]["is_demo"] is True
    assert payload["verdict"] == EMPTY_SAFE_TO_SEED


def test_inspect_rejects_mismatched_tenant_id(db, demo_tenant):
    with pytest.raises(CommandError, match="does not match"):
        call_command(
            "inspect_demo_tenant", tenant_slug=demo_tenant.slug,
            tenant_id="00000000-0000-0000-0000-000000000000",
        )
