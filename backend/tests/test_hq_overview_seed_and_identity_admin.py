import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.clinical.models import ClinicalCondition, ClinicalObservation
from apps.fhir.models import FHIRIdempotencyRecord
from apps.identity.models import Role, User, UserRole
from apps.platform.admin_shell import build_hq_dashboard_context
from apps.prescription.models import Prescription
from apps.tenancy.models import Tenant
from apps.terminology.models import FHIRCodeSystemRegistration, FHIRValueSetRegistration

pytestmark = pytest.mark.django_db


def make_manager(*, tenant, username="hq-identity-manager"):
    user = User.objects.create_user(
        username=username,
        password="identity-test-password",
        tenant=tenant,
    )
    role = Role.all_objects.create(
        tenant=tenant,
        code=f"{username}-role",
        name=f"{username} role",
        capabilities=["identity.manage"],
    )
    UserRole.all_objects.create(tenant=tenant, user=user, role=role)
    return user


def test_hq_seed_fills_overview_metrics_without_blanks(django_user_model):
    tenant = Tenant.objects.create(
        name="HQ Overview Seed Tenant",
        slug="hq-overview-seed",
        status=Tenant.STATUS_ACTIVE,
    )
    admin = django_user_model.objects.create_user(
        username="hq-overview-admin",
        password="test-password",
        is_platform_admin=True,
    )
    call_command("seed_hq_workspaces", tenant_slug=tenant.slug, verbosity=0)

    context = build_hq_dashboard_context(admin, tenant.pk)

    assert all(item.get("href") for item in context["metrics"])
    assert all(item.get("href") for item in context["attention_items"])
    assert all(item.get("href") for item in context["data_summary"])
    assert all(item["value"] > 0 for item in context["metrics"])
    assert all(item["value"] > 0 for item in context["attention_items"])
    assert all(item["value"] > 0 for item in context["data_summary"])

    assert ClinicalCondition.all_objects.filter(tenant=tenant).exists()
    assert ClinicalObservation.all_objects.filter(tenant=tenant).exists()
    assert Prescription.all_objects.filter(
        tenant=tenant,
        prescription_number="HQ-DEMO-RX-OPEN",
    ).exists()
    assert FHIRCodeSystemRegistration.all_objects.filter(tenant=tenant).exists()
    assert FHIRValueSetRegistration.all_objects.filter(tenant=tenant).exists()
    assert FHIRIdempotencyRecord.all_objects.filter(tenant=tenant).exists()
    assert User.objects.filter(tenant=tenant, username__startswith="hq-demo-").count() >= 6


def test_identity_user_lifecycle_create_suspend_disable_reset_and_roles():
    tenant = Tenant.objects.create(name="Identity Admin Tenant", slug="identity-admin")
    manager = make_manager(tenant=tenant)
    operator_role = Role.all_objects.create(
        tenant=tenant,
        code="OPS",
        name="Ops",
        capabilities=["inventory.read"],
    )
    pharmacist_role = Role.all_objects.create(
        tenant=tenant,
        code="RPH",
        name="Pharmacist",
        capabilities=["dispensing.read"],
    )

    client = APIClient()
    client.force_authenticate(user=manager)

    created = client.post(
        "/api/identity/users/",
        {
            "username": "new-operator",
            "email": "new-operator@example.com",
            "first_name": "New",
            "last_name": "Operator",
            "role_ids": [str(operator_role.pk)],
        },
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert created.status_code == 201
    body = created.json()
    user_id = body["id"]
    assert body["account_status"] == "ACTIVE"
    assert body["temporary_password"]
    assert {role["code"] for role in body["assigned_roles"]} == {"OPS"}

    listed = client.get(
        "/api/identity/users/?search=new-operator&category=ACTIVE&page_size=20",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1
    assert listed.json()["results"][0]["username"] == "new-operator"

    suspended = client.post(
        f"/api/identity/users/{user_id}/suspend/",
        {},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert suspended.status_code == 200
    assert suspended.json()["account_status"] == "SUSPENDED"
    assert suspended.json()["is_active"] is False

    activated = client.post(
        f"/api/identity/users/{user_id}/activate/",
        {},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert activated.status_code == 200
    assert activated.json()["account_status"] == "ACTIVE"

    roles = client.post(
        f"/api/identity/users/{user_id}/set-roles/",
        {"role_ids": [str(pharmacist_role.pk)]},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert roles.status_code == 200
    assert {role["code"] for role in roles.json()["assigned_roles"]} == {"RPH"}

    reset = client.post(
        f"/api/identity/users/{user_id}/reset-password/",
        {},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert reset.status_code == 200
    assert reset.json()["temporary_password"]
    assert reset.json()["must_change_password"] is True

    disabled = client.post(
        f"/api/identity/users/{user_id}/disable/",
        {},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert disabled.status_code == 200
    assert disabled.json()["account_status"] == "DISABLED"
