import pytest
from django.contrib.auth import get_user_model

from apps.customers.models import Customer
from apps.patients.models import Patient
from apps.tenancy.models import Tenant
from apps.workflows.models import DomainEvent


@pytest.mark.django_db
def test_platform_admin_sees_platform_hq_dashboard(client):
    user = get_user_model().objects.create_superuser(
        username="hq-admin",
        email="hq-admin@example.test",
        password="safe-test-password",
    )
    client.force_login(user)

    response = client.get("/admin-shell/")

    assert response.status_code == 200
    assert b"Platform overview" in response.content
    assert b"TibaTrace health operations" in response.content
    assert b"Operations" in response.content
    assert b"platform/hq.css" in response.content


@pytest.mark.django_db
def test_platform_admin_can_load_hq_overview_api(client):
    user = get_user_model().objects.create_superuser(
        username="hq-api-admin",
        email="hq-api-admin@example.test",
        password="safe-test-password",
    )
    client.force_login(user)

    response = client.get("/api/hq/overview/")

    assert response.status_code == 200
    assert response.json()["scope_label"] == "Platform overview"
    assert response.json()["is_platform_overview"] is True
    assert response.json()["metrics"][0]["label"] == "Active tenants"
    assert response.json()["generated_at"]
    assert response.json()["network_items"] == []


@pytest.mark.django_db
def test_platform_admin_can_load_all_hq_workspace_domains(client):
    tenant = Tenant.objects.create(name="HQ Demo", slug="hq-demo")
    Patient.all_objects.create(
        tenant=tenant,
        internal_reference_id="HQ-PAT-001",
        patient_number="TT-001",
        first_name="Amina",
        last_name="Kamau",
        verification_status="VERIFIED",
    )
    DomainEvent.all_objects.create(
        tenant=tenant,
        aggregate_type="Prescription",
        aggregate_id=tenant.id,
        event_type="PrescriptionCreated",
        status="PENDING",
    )
    customer = Customer.all_objects.create(
        tenant=tenant,
        customer_number="HQ-CUS-001",
        legal_name="HQ Demo Pharmacy",
        customer_type=Customer.CustomerType.PHARMACY,
    )
    user = get_user_model().objects.create_superuser(
        username="hq-workspace-admin",
        email="hq-workspace-admin@example.test",
        password="safe-test-password",
    )
    client.force_login(user)

    response = client.get("/api/hq/workspace/")

    assert response.status_code == 200
    body = response.json()
    assert body["people"]["counts"]["patients"] == 1
    assert body["people"]["patients"][0]["full_name"] == "Amina Kamau"
    assert body["catalogue"]["counts"]["skus"] == 0
    assert body["commerce"]["counts"]["orders"] == 0
    assert body["governance"]["counts"]["domain_events"] == 1
    assert body["governance"]["domain_events"][0]["event_type"] == "PrescriptionCreated"
    modules = {module["key"]: module for module in body["business_modules"]}
    assert {
        "customers",
        "requisitions",
        "sales-orders",
        "prescriptions",
    }.issubset(modules)
    customer_item = modules["customers"]["records"][0]
    assert customer_item["id"] == str(customer.id)
    assert customer_item["tenant_id"] == str(tenant.id)
    assert customer_item["actions"][0]["key"] == "approve-customer"


@pytest.mark.django_db
def test_tenant_operator_hq_workspace_is_tenant_scoped(client):
    tenant_a = Tenant.objects.create(name="Tenant A", slug="workspace-tenant-a")
    tenant_b = Tenant.objects.create(name="Tenant B", slug="workspace-tenant-b")
    Patient.all_objects.create(
        tenant=tenant_a,
        internal_reference_id="A-PAT-001",
        first_name="Amina",
        last_name="A",
    )
    Patient.all_objects.create(
        tenant=tenant_b,
        internal_reference_id="B-PAT-001",
        first_name="Baraka",
        last_name="B",
    )
    user = get_user_model().objects.create_user(
        username="tenant-hq-operator",
        email="tenant-hq@example.test",
        password="safe-test-password",
        tenant=tenant_a,
    )
    client.force_login(user)

    response = client.get("/api/hq/workspace/")

    assert response.status_code == 200
    body = response.json()
    assert body["people"]["counts"]["patients"] == 1
    assert [patient["full_name"] for patient in body["people"]["patients"]] == [
        "Amina A"
    ]
