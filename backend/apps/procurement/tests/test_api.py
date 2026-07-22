import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.procurement.services import SupplierGovernanceService
from apps.tenancy.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_procurement_api_endpoints_and_tenant_isolation():
    tenant_a = Tenant.objects.create(name="Tenant A", slug="proc-tenant-a")
    tenant_b = Tenant.objects.create(name="Tenant B", slug="proc-tenant-b")

    user_a = User.objects.create_user(username="proca", email="proca@test.com", password="password123", tenant=tenant_a)  # nosec B106
    user_b = User.objects.create_user(username="procb", email="procb@test.com", password="password123", tenant=tenant_b)  # nosec B106

    sup_a = SupplierGovernanceService.create_supplier(tenant=tenant_a, supplier_code="SUP-A", legal_name="Supplier Tenant A")
    sup_b = SupplierGovernanceService.create_supplier(tenant=tenant_b, supplier_code="SUP-B", legal_name="Supplier Tenant B")

    assert sup_a.supplier_code == "SUP-A"
    assert sup_b.supplier_code == "SUP-B"

    client = APIClient()

    # User A listing suppliers receives Tenant A's supplier only
    client.force_authenticate(user=user_a)
    res_a = client.get("/api/procurement/suppliers/", HTTP_X_TENANT_ID=str(tenant_a.pk))
    assert res_a.status_code == 200
    results_a = res_a.data if isinstance(res_a.data, list) else res_a.data.get("results", [])
    assert len(results_a) == 1
    assert results_a[0]["supplier_code"] == "SUP-A"

    # User B listing suppliers receives Tenant B's supplier only
    client.force_authenticate(user=user_b)
    res_b = client.get("/api/procurement/suppliers/", HTTP_X_TENANT_ID=str(tenant_b.pk))
    assert res_b.status_code == 200
    results_b = res_b.data if isinstance(res_b.data, list) else res_b.data.get("results", [])
    assert len(results_b) == 1
    assert results_b[0]["supplier_code"] == "SUP-B"
