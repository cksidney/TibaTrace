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
