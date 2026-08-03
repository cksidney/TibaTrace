"""The release migration inventory must fail closed, never report a false empty.

A release once shipped evidence claiming no migrations while carrying one,
because the generator scraped `migrate --plan` text and the command had failed
behind `|| true`. These tests pin the behaviours that make that impossible:
an unset input is an error, an unknown migration is an error, and a destructive
migration needs an explicit declaration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SCRIPT = REPO_ROOT / "scripts" / "migration_evidence.py"

#: The scalar release migration reference for baseline testing.
RELEASE_MIGRATION = "backend/apps/platform/migrations/0002_posrelease_client_alignment.py"

#: The full list of migrations this release introduces over the deployed baseline.
RELEASE_MIGRATIONS = [
    "backend/apps/integrations/migrations/0001_initial.py",
    "backend/apps/integrations/migrations/0002_claim_fields.py",
    "backend/apps/integrations/migrations/0003_activation_state_update.py",
    "backend/apps/integrations/migrations/__init__.py",
    "backend/apps/inventory/recalls/migrations/0001_initial.py",
    "backend/apps/inventory/recalls/migrations/__init__.py",
    "backend/apps/notifications/migrations/0002_nif_notifications.py",
    "backend/apps/pharmacy_network/migrations/0003_nif_premises_verification.py",
    "backend/apps/platform/migrations/0002_posrelease_client_alignment.py",
    # Stage 1 demo foundation.
    "backend/apps/tenancy/migrations/0003_tenant_is_demo.py",
    "backend/apps/platform/migrations/0003_demo_scenario_ownership.py",
    # Stage 2A master data: departments and their memberships. Additive only --
    # two new tables, no alteration to an existing one.
    "backend/apps/organizations/migrations/0002_departments.py",
    "backend/apps/platform/migrations/0004_demo_story_metadata.py",
    # Stage 2A service closure: segregation of duties on supplier qualifications.
    # Additive only -- four nullable columns, no alteration to existing data.
    "backend/apps/procurement/migrations/0005_supplier_qualification_governance.py",
]


def run(new_files: str | None, out: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "PYTHONPATH": str(BACKEND_ROOT),
        "DJANGO_SETTINGS_MODULE": "dawatrace.settings.base",
        "DAWATRACE_SECRET_KEY": "test-only-not-a-secret",
    }
    if new_files is not None:
        env["TIBATRACE_NEW_MIGRATION_FILES"] = new_files
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(out), *extra],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_release_migration_is_classified_correctly(tmp_path):
    out = tmp_path / "MIGRATIONS.json"
    result = run(RELEASE_MIGRATION, out)
    assert result.returncode == 0, result.stderr

    entry = json.loads(out.read_text())[0]
    assert entry["app"] == "platform"
    assert entry["migration"] == "0002_posrelease_client_alignment"
    assert entry["operation_count"] == 2
    assert entry["operation_types"] == ["AddField", "AddField"]
    assert entry["destructive"] is False
    assert entry["data_migration"] is False
    assert entry["sql_operation"] is False
    assert entry["source_path"] == RELEASE_MIGRATION


def test_unset_input_fails_rather_than_reporting_zero(tmp_path):
    """The exact defect: no input must not mean "no migrations"."""

    out = tmp_path / "MIGRATIONS.json"
    result = run(None, out)
    assert result.returncode != 0
    assert "TIBATRACE_NEW_MIGRATION_FILES" in result.stderr
    assert not out.exists()


def test_unknown_migration_fails(tmp_path):
    out = tmp_path / "MIGRATIONS.json"
    result = run("backend/apps/platform/migrations/9999_does_not_exist.py", out)
    assert result.returncode != 0
    assert "cannot see it" in result.stderr
    assert not out.exists()


def test_non_migration_path_fails(tmp_path):
    out = tmp_path / "MIGRATIONS.json"
    result = run("backend/apps/platform/models.py", out)
    assert result.returncode != 0
    assert "not a migration path" in result.stderr


def test_migrations_package_marker_is_not_a_migration(tmp_path):
    """A new Django app adds migrations/__init__.py; that is not a migration.

    v1.0.0-rc12 added four apps' migration packages, and the generator rejected
    the release because Django's loader -- correctly -- had never heard of
    integrations.__init__.
    """

    out = tmp_path / "MIGRATIONS.json"
    result = run(
        "backend/apps/integrations/migrations/__init__.py\n" + RELEASE_MIGRATION,
        out,
    )
    assert result.returncode == 0, result.stderr
    entries = json.loads(out.read_text())
    assert [e["migration"] for e in entries] == ["0002_posrelease_client_alignment"]


def test_only_package_markers_yields_empty_inventory(tmp_path):
    out = tmp_path / "MIGRATIONS.json"
    result = run("backend/apps/integrations/migrations/__init__.py", out)
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text()) == []


def test_empty_input_produces_empty_inventory_explicitly(tmp_path):
    """An empty list is legitimate only when the caller says so deliberately."""

    out = tmp_path / "MIGRATIONS.json"
    result = run("", out)
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text()) == []


def test_destructive_migration_requires_explicit_declaration(tmp_path, monkeypatch):
    """A RemoveField release must not pass silently."""

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import migration_evidence as me

    fake = [
        {
            "app": "platform", "migration": "0003_drop_a_column",
            "operation_count": 1, "operation_types": ["RemoveField"],
            "reversible": True, "destructive": True,
            "destructive_operations": ["RemoveField"],
            "data_migration": False, "sql_operation": False,
            "source_path": "backend/apps/platform/migrations/0003_drop_a_column.py",
        }
    ]
    monkeypatch.setattr(me, "build_inventory", lambda _files: fake)
    monkeypatch.setenv("TIBATRACE_NEW_MIGRATION_FILES", fake[0]["source_path"])
    out = tmp_path / "MIGRATIONS.json"

    monkeypatch.setattr(sys, "argv", ["migration_evidence.py", "--output", str(out)])
    with pytest.raises(me.EvidenceError, match="without an explicit declaration"):
        me.main()
    assert not out.exists()

    # With the declaration it proceeds, and records what makes it destructive.
    monkeypatch.setattr(
        sys, "argv",
        ["migration_evidence.py", "--output", str(out), "--allow-destructive"],
    )
    assert me.main() == 0
    assert json.loads(out.read_text())[0]["destructive_operations"] == ["RemoveField"]


def test_destructive_classification_unit():
    """Classification sets are the security-relevant part; assert them directly."""

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import migration_evidence as me

    assert "RemoveField" in me.DESTRUCTIVE_OPERATIONS
    assert "DeleteModel" in me.DESTRUCTIVE_OPERATIONS
    assert "RunPython" in me.DATA_MIGRATION_OPERATIONS
    assert "RunSQL" in me.SQL_OPERATIONS
    # AddField must never be treated as destructive, or every release blocks.
    assert "AddField" not in me.DESTRUCTIVE_OPERATIONS


def test_git_baseline_matches_the_declared_release_migration():
    """The inventory input must agree with what Git says the release adds.

    Guards the case where MIGRATIONS.json is populated from a stale or wrong
    baseline and silently omits a migration that is really in the release.
    """

    # The deployed baseline moves as releases ship. This test pins the
    # *mechanism* -- that git and the declared list agree -- not a frozen list,
    # which went stale the moment the next release added a migration.
    baseline = "24a160214114575bdbbb3059b10ad4e323f3daec"
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", f"{baseline}..HEAD",
         "--", "backend/apps/*/migrations/*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip("baseline commit not present in this checkout")
    added = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    # Also check untracked migration files if working tree is uncommitted
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "backend/apps/*/migrations/*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if untracked.returncode == 0:
        for u in untracked.stdout.splitlines():
            if u.strip() and u.strip() not in added:
                added.append(u.strip())

    assert sorted(added) == sorted(RELEASE_MIGRATIONS), added
