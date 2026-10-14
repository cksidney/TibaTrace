"""Navigation grants never turn a tenant administrator into a platform owner."""
import pytest
from rest_framework.test import APIClient

from apps.identity.models import AttributePolicy, Role, User, UserRole
from apps.platform.navigation_access import OWNER_VIEWS, TENANT_VIEWS, hq_navigation_access
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def actor():
    tenant = Tenant.objects.create(name="Navigation tenant", slug="navigation-tenant")
    user = User.objects.create_user(username="tenant-manager", tenant=tenant)
    role = Role.all_objects.create(tenant=tenant, code="TENANT_ADMIN", name="Tenant administrator", capabilities=[])
    binding = UserRole.all_objects.create(tenant=tenant, user=user, role=role)
    client = APIClient()
    client.force_login(user)
    return tenant, user, role, binding, client


def grant(actor, capabilities):
    role = actor[2]
    role.capabilities = capabilities
    role.save(update_fields=["capabilities"])


def test_unprivileged_tenant_only_gets_overview(actor):
    response = actor[4].get("/api/hq/overview/")
    assert response.status_code == 200
    body = response.json()
    assert body["allowed_views"] == ["overview"]
    assert not body["is_platform_owner"]
    assert not body["show_pos_handoff"]
    for field in ("metrics", "attention_items", "data_summary"):
        assert all(row.get("href", "#overview") == "#overview" for row in body[field])


@pytest.mark.parametrize("view,capabilities", list(TENANT_VIEWS.items()))
def test_tenant_menu_uses_effective_capabilities(actor, view, capabilities):
    grant(actor, [capabilities[0]])
    body = actor[4].get("/api/hq/overview/").json()
    assert view in body["allowed_views"]
    assert not set(OWNER_VIEWS) & set(body["allowed_views"])
    assert not body["is_platform_owner"]


def test_wildcard_tenant_retains_tenant_workflows_but_not_owner_tools(actor):
    grant(actor, ["*"])
    body = actor[4].get("/api/hq/overview/").json()
    assert set(body["allowed_views"]) == {"overview", "gs1", *TENANT_VIEWS}
    assert body["show_pos_handoff"]
    assert not body["is_platform_owner"]
    assert actor[4].get("/api/identity/session/").json()["user"]["is_platform_owner"] is False


@pytest.mark.parametrize("path", [
    "/api/nif/platform/providers/", "/api/nif/platform/activations/",
    "/api/nif/platform/evidence/", "/api/nif/platform/reports/", "/api/nif/platform/recalls/",
])
def test_wildcard_tenant_cannot_call_owner_apis(actor, path):
    grant(actor, ["*"])
    assert actor[4].get(path).status_code == 403


def test_wildcard_tenant_cannot_register_another_pharmacy(actor):
    grant(actor, ["*"])
    response = actor[4].post("/api/pharmacy-network/pharmacies/", {}, format="json")
    assert response.status_code == 403


def test_revocation_and_attribute_deny_take_effect_on_next_overview(actor):
    tenant, _, _, binding, client = actor
    grant(actor, ["reports.view", "inventory.read"])
    assert "reports" in client.get("/api/hq/overview/").json()["allowed_views"]
    AttributePolicy.all_objects.create(
        tenant=tenant, code="deny-reports", capability="reports.view",
        effect=AttributePolicy.EFFECT_DENY,
    )
    allowed = client.get("/api/hq/overview/").json()["allowed_views"]
    assert "reports" not in allowed
    assert "inventory" in allowed
    binding.is_active = False
    binding.save(update_fields=["is_active"])
    assert client.get("/api/hq/overview/").json()["allowed_views"] == ["overview"]


def test_gs1_needs_both_catalogue_and_inventory_read_access(actor):
    grant(actor, ["catalogue.read"])
    assert "gs1" not in actor[4].get("/api/hq/overview/").json()["allowed_views"]
    grant(actor, ["catalogue.read", "inventory.read"])
    assert "gs1" in actor[4].get("/api/hq/overview/").json()["allowed_views"]


@pytest.mark.parametrize("capability", ["recalls.read", "recalls.manage", "compliance.officer", "inventory.read", "inventory.manage"])
def test_recall_navigation_matches_actual_tenant_api_permission(actor, capability):
    grant(actor, [capability])
    assert "regulatory" in actor[4].get("/api/hq/overview/").json()["allowed_views"]
    assert actor[4].get("/api/nif/recalls/impacts/").status_code == 200
    assert actor[4].get("/api/nif/platform/recalls/").status_code == 403


def test_practitioner_access_does_not_imply_recall_permission(actor):
    grant(actor, ["practitioners.read"])
    allowed = actor[4].get("/api/hq/overview/").json()["allowed_views"]
    assert "people" in allowed
    assert "regulatory" not in allowed
    assert actor[4].get("/api/nif/recalls/impacts/").status_code == 403


@pytest.mark.parametrize("flag", ["is_platform_admin", "is_superuser"])
def test_explicit_owner_keeps_all_tools_even_in_selected_tenant(actor, flag):
    owner = User.objects.create_user(username=f"owner-{flag}", **{flag: True})
    client = APIClient()
    client.force_login(owner)
    for headers in ({}, {"HTTP_X_TENANT_ID": str(actor[0].pk)}):
        body = client.get("/api/hq/overview/", **headers).json()
        assert body["is_platform_owner"]
        assert set(body["allowed_views"]) == {"overview", "gs1", *TENANT_VIEWS, *OWNER_VIEWS}
        assert body["show_pos_handoff"]
        assert body["tenant_id"] == headers.get("HTTP_X_TENANT_ID", "")
    assert client.get("/api/identity/session/").json()["user"]["is_platform_owner"] is True


def test_tenant_header_cannot_spoof_owner_or_another_tenant(actor):
    other = Tenant.objects.create(name="Other navigation tenant", slug="other-navigation")
    grant(actor, ["*"])
    response = actor[4].get("/api/hq/overview/", HTTP_X_TENANT_ID=str(other.pk))
    assert response.status_code == 403
    access = hq_navigation_access(actor[1], other.pk)
    assert access["allowed_views"] == ["overview"]
    assert not access["show_pos_handoff"]


def test_inactive_user_gets_no_navigation(actor):
    grant(actor, ["*"])
    actor[1].is_active = False
    access = hq_navigation_access(actor[1], actor[0].pk)
    assert access == {"allowed_views": [], "is_platform_owner": False, "show_pos_handoff": False}


def test_legacy_shell_uses_same_policy(actor, client):
    client.force_login(actor[1])
    body = client.get("/admin-shell/").content.decode()
    assert 'href="/api/docs/"' not in body
    assert 'href="/#access"' not in body
    assert 'href="/pos/"' not in body
    grant(actor, ["identity.manage", "pos.shift.manage"])
    body = client.get("/admin-shell/").content.decode()
    assert "Tenant users &amp; access" in body or "Tenant users & access" in body
    assert 'href="/pos/"' in body
    assert 'href="/api/docs/"' not in body


def test_superuser_without_platform_flag_can_sign_in():
    user = User.objects.create_superuser(username="explicit-super-owner", password="Synthetic-password-1234")
    assert not user.is_platform_admin
    response = APIClient().post(
        "/api/identity/session/", {"username": user.username, "password": "Synthetic-password-1234"}, format="json",
    )
    assert response.status_code == 200
    assert response.json()["user"]["is_platform_owner"]
