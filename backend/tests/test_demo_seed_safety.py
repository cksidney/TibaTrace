"""Demo seeders must never run against production, and must never leak a password.

These commands create privileged accounts -- a CDS approver can authorise
clinical decisions -- so the guard is treated as a security control and tested
as one. The literals that used to live in the command modules are asserted
absent from tracked source, not merely unused.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.demo_seed import (
    DEMO_PASSWORD_ENV_VAR,
    PRODUCTION_ENVIRONMENTS,
    generate_demo_password,
    resolve_demo_password,
)
from apps.identity.models import UserRole
from apps.tenancy.models import Tenant

DEMO_COMMANDS = ("seed_pos_dispensing_demo", "seed_hq_workspaces")

#: The credentials removed by this change, assembled at runtime rather than
#: written out. History was rewritten so these strings appear nowhere in any
#: reachable commit, and spelling them here verbatim would put them straight
#: back. Concatenation keeps the guard working without reintroducing the value.
RETIRED_LITERALS = (
    "Demo" + "Till" + "!Pass" + "123",
    "Hq" + "Demo" + "!Pass" + "123",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def demo_tenant(db):
    return Tenant.objects.create(
        name="Demo Seed Safety",
        slug="demo-seed-safety",
        status=Tenant.STATUS_ACTIVE,
    )


# --------------------------------------------------------------------------
# Production refusal
# --------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("command", DEMO_COMMANDS)
@pytest.mark.parametrize("environment", sorted(PRODUCTION_ENVIRONMENTS))
def test_refuses_to_run_in_production(settings, command, environment):
    settings.DAWATRACE_ENV = environment
    settings.DEBUG = False
    with pytest.raises(CommandError, match="never permitted"):
        call_command(command)


@pytest.mark.django_db
@pytest.mark.parametrize("command", DEMO_COMMANDS)
@pytest.mark.parametrize("environment", sorted(PRODUCTION_ENVIRONMENTS))
def test_allow_demo_seed_does_not_override_production(settings, command, environment):
    """The explicit flag is never sufficient against a production environment."""

    settings.DAWATRACE_ENV = environment
    settings.DEBUG = False
    with pytest.raises(CommandError, match="never permitted"):
        call_command(command, "--allow-demo-seed")


@pytest.mark.django_db
@pytest.mark.parametrize("command", DEMO_COMMANDS)
def test_debug_does_not_override_production(settings, command):
    """DEBUG=True on a production environment is still a refusal."""

    settings.DAWATRACE_ENV = "production"
    settings.DEBUG = True
    with pytest.raises(CommandError, match="never permitted"):
        call_command(command)


@pytest.mark.django_db
@pytest.mark.parametrize("command", DEMO_COMMANDS)
def test_case_and_whitespace_do_not_bypass_the_guard(settings, command):
    settings.DAWATRACE_ENV = "  PRODUCTION  "
    settings.DEBUG = False
    with pytest.raises(CommandError, match="never permitted"):
        call_command(command, "--allow-demo-seed")


# --------------------------------------------------------------------------
# Non-production intent
# --------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("command", DEMO_COMMANDS)
def test_refuses_outside_debug_without_the_flag(settings, command):
    settings.DAWATRACE_ENV = "staging"
    settings.DEBUG = False
    with pytest.raises(CommandError, match="--allow-demo-seed"):
        call_command(command)


@pytest.mark.django_db
def test_runs_in_local_development(settings, demo_tenant):
    settings.DAWATRACE_ENV = "development"
    settings.DEBUG = True
    call_command("seed_pos_dispensing_demo", "--tenant", demo_tenant.slug, stdout=io.StringIO())
    assert get_user_model().objects.filter(username="demo_dispensing_rph").exists()


# --------------------------------------------------------------------------
# Credential handling
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_missing_password_variable_fails_outside_debug(settings, monkeypatch):
    settings.DAWATRACE_ENV = "staging"
    settings.DEBUG = False
    monkeypatch.delenv(DEMO_PASSWORD_ENV_VAR, raising=False)
    with pytest.raises(CommandError, match=DEMO_PASSWORD_ENV_VAR):
        resolve_demo_password()


@pytest.mark.django_db
def test_supplied_password_is_used_and_validated(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.setenv(DEMO_PASSWORD_ENV_VAR, "a-sufficiently-long-demo-password")
    password, generated = resolve_demo_password()
    assert password == "a-sufficiently-long-demo-password"
    assert generated is False


@pytest.mark.django_db
def test_weak_supplied_password_is_rejected(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.setenv(DEMO_PASSWORD_ENV_VAR, "1234")
    with pytest.raises(CommandError, match="failed password validation"):
        resolve_demo_password()


@pytest.mark.django_db
def test_generated_password_only_under_debug(settings, monkeypatch):
    monkeypatch.delenv(DEMO_PASSWORD_ENV_VAR, raising=False)
    settings.DEBUG = True
    password, generated = resolve_demo_password()
    assert generated is True
    assert len(password) >= 20


def test_generated_passwords_are_not_predictable():
    assert generate_demo_password() != generate_demo_password()


@pytest.mark.django_db
def test_supplied_password_is_never_echoed(settings, monkeypatch, demo_tenant):
    """A supplied credential must not appear in command output."""

    settings.DAWATRACE_ENV = "development"
    settings.DEBUG = True
    secret = "never-print-this-demo-password"
    monkeypatch.setenv(DEMO_PASSWORD_ENV_VAR, secret)
    out = io.StringIO()
    call_command("seed_pos_dispensing_demo", "--tenant", demo_tenant.slug, stdout=out)
    captured = out.getvalue()
    assert secret not in captured
    assert DEMO_PASSWORD_ENV_VAR in captured
    # Usernames and roles remain visible -- the summary is still useful.
    assert "demo_dispensing_rph" in captured
    assert "demo_cds_approver" in captured


@pytest.mark.django_db
def test_no_retired_literal_appears_in_output(settings, demo_tenant, monkeypatch):
    settings.DAWATRACE_ENV = "development"
    settings.DEBUG = True
    monkeypatch.delenv(DEMO_PASSWORD_ENV_VAR, raising=False)
    out = io.StringIO()
    call_command("seed_pos_dispensing_demo", "--tenant", demo_tenant.slug, stdout=out)
    captured = out.getvalue()
    for literal in RETIRED_LITERALS:
        assert literal not in captured


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_running_twice_creates_no_duplicate_users_or_roles(settings, demo_tenant):
    settings.DAWATRACE_ENV = "development"
    settings.DEBUG = True
    user_model = get_user_model()

    call_command("seed_pos_dispensing_demo", "--tenant", demo_tenant.slug, stdout=io.StringIO())
    users_after_first = user_model.objects.filter(username__startswith="demo_").count()
    roles_after_first = UserRole.all_objects.count()

    call_command("seed_pos_dispensing_demo", "--tenant", demo_tenant.slug, stdout=io.StringIO())
    assert user_model.objects.filter(username__startswith="demo_").count() == users_after_first
    assert UserRole.all_objects.count() == roles_after_first
    assert user_model.objects.filter(username="demo_dispensing_rph").count() == 1


@pytest.mark.django_db
def test_existing_user_is_reused_not_duplicated(settings, demo_tenant):
    settings.DAWATRACE_ENV = "development"
    settings.DEBUG = True
    user_model = get_user_model()
    existing = user_model.objects.create(username="demo_dispensing_rph", tenant=demo_tenant)

    call_command("seed_pos_dispensing_demo", "--tenant", demo_tenant.slug, stdout=io.StringIO())
    assert user_model.objects.filter(username="demo_dispensing_rph").count() == 1
    assert user_model.objects.get(username="demo_dispensing_rph").pk == existing.pk


# --------------------------------------------------------------------------
# Source-level regression
# --------------------------------------------------------------------------


def test_retired_literals_are_absent_from_tracked_source():
    """The removed passwords must not reappear anywhere under backend/."""

    offenders: list[str] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        if any(part in {".venv", ".venv-win", "__pycache__", "node_modules"} for part in path.parts):
            continue
        if path.name == Path(__file__).name:
            continue  # this module names them deliberately
        text = path.read_text(encoding="utf-8", errors="ignore")
        for literal in RETIRED_LITERALS:
            if literal in text:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {literal}")
    assert offenders == []


def test_demo_commands_call_the_guard():
    """Every demo seeder must invoke the shared gate before doing any work."""

    command_paths = list(BACKEND_ROOT.glob("apps/*/management/commands/seed_*demo*.py"))
    command_paths += [BACKEND_ROOT / "apps/platform/management/commands/seed_hq_workspaces.py"]
    checked = 0
    for path in command_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if "set_password" not in text:
            continue
        checked += 1
        assert "ensure_demo_seed_allowed" in text, f"{path.name} sets a password without the guard"
        assert re.search(r"set_password\(\s*[\"']", text) is None, (
            f"{path.name} passes a string literal to set_password"
        )
    assert checked >= 2
