import pytest

from apps.tenancy.models import Tenant


@pytest.mark.django_db
def test_platform_admin_can_manage_tenant_lifecycle(client, django_user_model):
    platform_admin = django_user_model.objects.create_user(
        username="tenant-platform-admin",
        password="tenant-platform-admin-password",
        is_platform_admin=True,
    )
    client.force_login(platform_admin)

    created = client.post(
        "/api/tenancy/tenants/",
        {
            "name": "Westlands Pharmacy Group",
            "slug": "westlands-pharmacy",
            "country_code": "KE",
            "time_zone": "Africa/Nairobi",
            "metadata": {"support_email": "ops@example.test"},
        },
        content_type="application/json",
    )
    assert created.status_code == 201
    tenant_id = created.json()["id"]

    updated = client.patch(
        f"/api/tenancy/tenants/{tenant_id}/",
        {"name": "Westlands Pharmacy Network"},
        content_type="application/json",
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Westlands Pharmacy Network"

    suspended = client.post(
        f"/api/tenancy/tenants/{tenant_id}/suspend/",
        {"reason": "Contract review"},
        content_type="application/json",
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == Tenant.STATUS_SUSPENDED
    assert suspended.json()["suspension_reason"] == "Contract review"

    activated = client.post(
        f"/api/tenancy/tenants/{tenant_id}/activate/",
        content_type="application/json",
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == Tenant.STATUS_ACTIVE


@pytest.mark.django_db
def test_tenant_operator_cannot_manage_other_tenants(client, django_user_model):
    tenant = Tenant.objects.create(name="Tenant A", slug="tenant-a")
    other = Tenant.objects.create(name="Tenant B", slug="tenant-b")
    operator = django_user_model.objects.create_user(
        username="tenant-operator",
        password="tenant-operator-password",
        tenant=tenant,
    )
    client.force_login(operator)

    listed = client.get("/api/tenancy/tenants/")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [str(tenant.id)]

    forbidden = client.post(
        f"/api/tenancy/tenants/{other.id}/suspend/",
        {"reason": "Not allowed"},
        content_type="application/json",
    )
    assert forbidden.status_code == 403
