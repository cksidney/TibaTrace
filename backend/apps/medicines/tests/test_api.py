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
def test_sku_barcode_lookup_endpoint():
    tenant = Tenant.objects.create(name="API Tenant", slug="api-tenant")
    user = User.objects.create_user(username="apiuser", email="apiuser@test.com", password="password123", tenant=tenant)  # nosec B106
    
    df = DoseForm.objects.create(code="TAB", name="Tablet")
    cmp = ClinicalMedicinalProduct.objects.create(
        tenant=tenant, code="CMP-PAR-500", canonical_name="Paracetamol 500 mg Tablet", dose_form=df
    )
    mp = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant, code="MP-PAN-500", brand_name="Panadol", clinical_product=cmp
    )
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box 100", unit_of_measure="tab")

    sku = CommercialSKU.objects.create(
        tenant=tenant,
        sku_code="SKU-LOOKUP-01",
        display_name="Panadol 500mg Pack",
        manufactured_product=mp,
        package_definition=pkg,
        default_barcode="789012345678",
        status="ACTIVE",
    )

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/medicines/skus/lookup/?barcode=789012345678", HTTP_X_TENANT_ID=str(tenant.pk))

    assert response.status_code == 200
    assert response.data["sku_code"] == "SKU-LOOKUP-01"
    assert response.data["brand_name"] == "Panadol"
    assert sku.sku_code == "SKU-LOOKUP-01"
