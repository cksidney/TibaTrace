"""What /api/tenancy/tenants/ is for now.

This file used to assert the lifecycle that no longer exists: create a tenant
and get a live pharmacy back in one POST, PATCH any field, suspend it, activate
it. Every step of that was a defect rather than a feature -- the created tenant
had no premises licence, no superintendent, no organization, no branch and
nobody who could sign in, and the suspension stopped nothing at all.

Administration moved to apps.pharmacy_network, where the transitions are guarded
and recorded; those paths are covered in test_pharmacy_network_api.py and
test_pharmacy_lifecycle.py. What remains here is the read surface, which the
scope picker and tenant switcher depend on.
"""
import pytest

from apps.pharmacy_network.services import PharmacyOnboardingService
from apps.tenancy.models import Tenant


@pytest.mark.django_db
def test_a_platform_admin_reads_every_tenant(client, django_user_model):
    admin = django_user_model.objects.create_user(
        username="tenant-platform-admin",
        password="tenant-platform-admin-password",
        is_platform_admin=True,
    )
    PharmacyOnboardingService.register_prospect(
        name="Westlands Pharmacy Group", slug="westlands-pharmacy",
        legal_name="Westlands Pharmacy Group Ltd",
    )
    client.force_login(admin)

    listed = client.get("/api/tenancy/tenants/")
    assert listed.status_code == 200
    assert any(row["slug"] == "westlands-pharmacy" for row in listed.json())


@pytest.mark.django_db
def test_an_operator_sees_only_their_own_tenant(client, django_user_model):
    mine = Tenant.objects.create(name="Mine", slug="mine")
    Tenant.objects.create(name="Theirs", slug="theirs")
    operator = django_user_model.objects.create_user(
        username="tenant-operator", password="tenant-operator-password", tenant=mine
    )
    client.force_login(operator)

    listed = client.get("/api/tenancy/tenants/")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [str(mine.id)]


@pytest.mark.django_db
def test_the_write_surface_is_gone(client, django_user_model):
    """The point of the change.

    A pharmacy created here would skip the licence check, the provisioning and
    the record of who decided.
    """
    admin = django_user_model.objects.create_user(
        username="tenant-writer", password="tenant-writer-password", is_platform_admin=True
    )
    client.force_login(admin)

    created = client.post(
        "/api/tenancy/tenants/",
        {"name": "Backdoor Pharmacy", "slug": "backdoor-pharmacy"},
        content_type="application/json",
    )
    assert created.status_code in (403, 405)
    assert not Tenant.objects.filter(slug="backdoor-pharmacy").exists()
