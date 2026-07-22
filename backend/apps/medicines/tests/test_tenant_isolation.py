import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.tenancy.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_tenant_isolation_and_cross_tenant_denial():
    tenant_a = Tenant.objects.create(name="Tenant A", slug="tenant-a")
    tenant_b = Tenant.objects.create(name="Tenant B", slug="tenant-b")

    user_a = User.objects.create_user(username="usera", email="user_a@test.com", password="password123", tenant=tenant_a)  # nosec B106
    user_b = User.objects.create_user(username="userb", email="user_b@test.com", password="password123", tenant=tenant_b)  # nosec B106

    df = DoseForm.objects.create(code="TAB", name="Tablet")
    cmp_a = ClinicalMedicinalProduct.objects.create(
        tenant=tenant_a, code="CMP-A", canonical_name="Product Tenant A", dose_form=df
    )
    mp_a = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant_a, code="MP-A", brand_name="Brand A", clinical_product=cmp_a
    )
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box 100", unit_of_measure="tab")

    sku_a = CommercialSKU.objects.create(
        tenant=tenant_a,
        sku_code="SKU-TENANT-A",
        display_name="SKU Tenant A",
        manufactured_product=mp_a,
        package_definition=pkg,
        default_barcode="111222333444",
        status="ACTIVE",
    )

    client = APIClient()

    # User B searching for Tenant A's SKU barcode gets 404
    client.force_authenticate(user=user_b)
    res_b = client.get("/api/medicines/skus/lookup/?barcode=111222333444", HTTP_X_TENANT_ID=str(tenant_b.pk))
    assert res_b.status_code == 404

    # User A searching for Tenant A's SKU barcode gets 200
    client.force_authenticate(user=user_a)
    res_a = client.get("/api/medicines/skus/lookup/?barcode=111222333444", HTTP_X_TENANT_ID=str(tenant_a.pk))
    assert res_a.status_code == 200
    assert res_a.data["sku_code"] == "SKU-TENANT-A"
    assert sku_a.sku_code == "SKU-TENANT-A"
