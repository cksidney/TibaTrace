import pytest
from rest_framework.test import APIClient

from apps.identity.models import Role, ServiceAccount, User, UserRole
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


def make_user(*, tenant, username, capabilities=()):
    user = User.objects.create_user(
        username=username,
        password="identity-test-password",
        tenant=tenant,
    )
    if capabilities:
        role = Role.all_objects.create(
            tenant=tenant,
            code=f"{username}-role",
            name=f"{username} role",
            capabilities=list(capabilities),
        )
        UserRole.all_objects.create(tenant=tenant, user=user, role=role)
    return user


def test_identity_management_requires_explicit_authority():
    tenant = Tenant.objects.create(name="Identity Tenant", slug="identity-tenant")
    ordinary = make_user(tenant=tenant, username="ordinary")
    client = APIClient()
    client.force_authenticate(user=ordinary)

    response = client.get(
        "/api/identity/users/",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )

    assert response.status_code == 403


def test_identity_management_is_tenant_scoped_and_reports_assignments():
    tenant = Tenant.objects.create(name="Identity Tenant", slug="identity-tenant")
    other = Tenant.objects.create(name="Other Identity Tenant", slug="other-identity-tenant")
    manager = make_user(
        tenant=tenant,
        username="identity-manager",
        capabilities=("identity.manage",),
    )
    member = make_user(tenant=tenant, username="tenant-member")
    make_user(tenant=other, username="other-member")
    ServiceAccount.all_objects.create(
        tenant=tenant,
        code="hq-export",
        display_name="HQ export",
        credential_fingerprint="a" * 64,
    )

    client = APIClient()
    client.force_authenticate(user=manager)
    users = client.get(
        "/api/identity/users/",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    matrix = client.get(
        "/api/identity/matrix/",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )

    assert users.status_code == 200
    body = users.json()
    rows = body["results"] if isinstance(body, dict) else body
    assert {row["username"] for row in rows} == {manager.username, member.username}
    assert matrix.status_code == 200
    assert matrix.json()["tenant_id"] == str(tenant.pk)
    assert matrix.json()["service_accounts"][0]["code"] == "hq-export"
    assert "catalogue" in matrix.json()
    assert "identity.manage" in matrix.json()["catalogue"]["capabilities"]


def test_role_capabilities_can_be_updated_by_identity_managers():
    tenant = Tenant.objects.create(name="Identity Tenant", slug="identity-tenant-patch")
    manager = make_user(
        tenant=tenant,
        username="identity-manager-patch",
        capabilities=("identity.manage",),
    )
    role = Role.all_objects.create(
        tenant=tenant,
        code="DISPENSE",
        name="Dispenser",
        capabilities=["dispensing.read"],
        is_system=True,
    )

    client = APIClient()
    client.force_authenticate(user=manager)
    response = client.patch(
        f"/api/identity/roles-detail/{role.pk}/",
        {"name": "Dispensing pharmacist", "capabilities": ["dispensing.read", "inventory.read"]},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Dispensing pharmacist"
    assert body["capabilities"] == ["dispensing.read", "inventory.read"]
    assert body["code"] == "DISPENSE"
    role.refresh_from_db()
    assert role.capabilities == ["dispensing.read", "inventory.read"]


def test_tenant_admin_can_create_role_and_assign_it_to_a_new_user():
    tenant = Tenant.objects.create(name="Identity Tenant", slug="identity-tenant-create-role")
    manager = make_user(
        tenant=tenant,
        username="identity-manager-create",
        capabilities=("identity.manage",),
    )
    client = APIClient()
    client.force_authenticate(user=manager)

    created_role = client.post(
        "/api/identity/roles-detail/",
        {
            "code": "branch_manager",
            "name": "Branch manager",
            "capabilities": ["inventory.read", "pos.shift.manage"],
        },
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert created_role.status_code == 201
    role_body = created_role.json()
    assert role_body["code"] == "BRANCH_MANAGER"
    assert role_body["is_system"] is False

    created_user = client.post(
        "/api/identity/users/",
        {
            "username": "branch.user",
            "first_name": "Branch",
            "last_name": "User",
            "role_ids": [role_body["id"]],
        },
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert created_user.status_code == 201
    user_body = created_user.json()
    assert user_body["username"] == "branch.user"
    assert any(role["code"] == "BRANCH_MANAGER" for role in user_body["assigned_roles"])
    assert "inventory.read" in user_body["effective_capabilities"]

    roles = client.get("/api/identity/roles-detail/", HTTP_X_TENANT_ID=str(tenant.pk))
    assert roles.status_code == 200
    codes = {row["code"] for row in roles.json()}
    assert "TENANT_ADMIN" in codes
    assert "BRANCH_MANAGER" in codes
