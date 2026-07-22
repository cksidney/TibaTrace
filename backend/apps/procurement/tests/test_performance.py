import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.core.tenant_context import set_current_tenant_id
from apps.procurement.services import SupplierGovernanceService
from apps.tenancy.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_procurement_bounded_query_assertions(django_assert_num_queries):
    tenant = Tenant.objects.create(name="Perf Proc Tenant", slug="perf-proc-tenant")
    user = User.objects.create_user(username="perfproc", email="perfproc@test.com", password="password123", tenant=tenant)  # nosec B106
    set_current_tenant_id(str(tenant.pk))

    for i in range(5):
        SupplierGovernanceService.create_supplier(tenant=tenant, supplier_code=f"SUP-PERF-{i}", legal_name=f"Supplier Perf {i}")

    client = APIClient()
    client.force_authenticate(user=user)

    with django_assert_num_queries(1):
        res = client.get("/api/procurement/suppliers/", HTTP_X_TENANT_ID=str(tenant.pk))
        assert res.status_code == 200
        results = res.data if isinstance(res.data, list) else res.data.get("results", [])
        assert len(results) == 5
