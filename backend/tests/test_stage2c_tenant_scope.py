"""Stage 2C branch lookups must be scoped to the scenario tenant.

The generator resolved a transfer's source and destination branches with
`Location.objects.get(pk=...)`. Two defects in one line:

* `objects` is tenant-strict, so outside a request it matches nothing and the
  lookup raises DoesNotExist for a branch that plainly exists.
* A bare pk lookup on a UUID is unscoped, so a branch id belonging to another
  tenant would resolve and the transfer would be raised against it.

The second is the one that matters: a stock transfer between tenants is not a
data-quality problem, it is stock leaving the organisation that owns it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from apps.organizations.models import Location
from apps.organizations.services import (
    OrganizationProvisioningService,
    SiteProvisioningService,
)
from apps.tenancy.models import Tenant

STAGE2C = (
    pathlib.Path(__file__).resolve().parents[1]
    / "apps" / "platform" / "demo" / "generation" / "stage2c.py"
)


@pytest.fixture
def two_tenants(db):
    """Two tenants, each with one branch, so a cross-tenant id exists."""
    made = {}
    for slug, code in (("scope-a", "A"), ("scope-b", "B")):
        tenant = Tenant.objects.create(name=f"Chemists {code}", slug=slug)
        org = OrganizationProvisioningService.provision_organization(
            tenant=tenant, code=f"{code}-ORG", name=f"Chemists {code} Ltd"
        )
        branch = SiteProvisioningService.provision_site(
            tenant=tenant, organization=org, code=f"{code}-BR", name=f"{code} Branch"
        )
        made[slug] = {"tenant": tenant, "branch": branch}
    return made


def _resolve(tenant, branch_id):
    """The lookup exactly as stage2c performs it after the fix."""
    return Location.all_objects.get(pk=branch_id, tenant=tenant)


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_same_tenant_source_and_destination_resolve(two_tenants):
    a = two_tenants["scope-a"]
    other = SiteProvisioningService.provision_site(
        tenant=a["tenant"],
        organization=a["branch"].organization,
        code="A-BR2", name="A Second Branch",
    )
    assert _resolve(a["tenant"], a["branch"].pk).pk == a["branch"].pk
    assert _resolve(a["tenant"], other.pk).pk == other.pk


def test_a_source_branch_from_another_tenant_is_refused(two_tenants):
    """A transfer sourced from another tenant's branch moves their stock."""
    a, b = two_tenants["scope-a"], two_tenants["scope-b"]
    with pytest.raises(Location.DoesNotExist):
        _resolve(a["tenant"], b["branch"].pk)


def test_a_destination_branch_from_another_tenant_is_refused(two_tenants):
    a, b = two_tenants["scope-a"], two_tenants["scope-b"]
    with pytest.raises(Location.DoesNotExist):
        _resolve(b["tenant"], a["branch"].pk)


def test_an_unknown_uuid_fails_cleanly(two_tenants):
    """Not-found behaviour is preserved: DoesNotExist, not a crash."""
    import uuid

    with pytest.raises(Location.DoesNotExist):
        _resolve(two_tenants["scope-a"]["tenant"], uuid.uuid4())


def test_the_strict_manager_would_have_found_nothing(two_tenants):
    """Why all_objects is required, not merely preferred.

    Outside a request nothing sets thread-local tenant context, so the strict
    manager matches nothing -- including the tenant's own branch.
    """
    a = two_tenants["scope-a"]
    assert Location.all_objects.filter(pk=a["branch"].pk).exists()
    assert not Location.objects.filter(pk=a["branch"].pk).exists()


# ---------------------------------------------------------------------------
# The source itself
# ---------------------------------------------------------------------------


def test_stage2c_resolves_branches_through_all_objects_with_a_tenant(two_tenants):
    """Reads the generator's own source, so the fix cannot regress silently."""
    tree = ast.parse(STAGE2C.read_text())
    branch_lookups = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "get":
            continue
        receiver = node.func.value
        if not isinstance(receiver, ast.Attribute):
            continue
        if "BranchLocation" not in ast.unparse(receiver):
            continue
        keywords = {kw.arg for kw in node.keywords}
        branch_lookups.append((receiver.attr, keywords))

    assert branch_lookups, "expected stage2c to resolve branches by id"
    for manager, keywords in branch_lookups:
        assert manager == "all_objects", f"branch lookup uses {manager}"
        assert "tenant" in keywords or "tenant_id" in keywords, (
            f"branch lookup is not tenant-scoped: {keywords}"
        )


def test_the_lookup_audit_reports_nothing_for_stage2c():
    from apps.prescription.management.lookup_safety import find_unscoped_uuid_lookups

    apps_root = pathlib.Path(__file__).resolve().parents[1] / "apps"
    findings = [
        f for f in find_unscoped_uuid_lookups(apps_root) if "stage2c" in f.path
    ]
    assert findings == [], findings


def test_no_audit_suppression_marker_was_used(two_tenants):
    """The fix must be a real fix, not a silenced audit."""
    source = STAGE2C.read_text()
    for marker in ("# tenant-safety:", "# noqa", "# nosec", "EXPLICIT_GLOBAL_MODELS"):
        assert marker not in source, f"stage2c.py carries a suppression: {marker}"
