import pytest
from django.utils import timezone

from apps.inventory.models import InventoryBatch, InventoryLocation
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location


@pytest.fixture
def branch(clinical_setup, tenant_a):
    return Location.all_objects.filter(tenant=tenant_a, code="MAIN").first()

@pytest.fixture
def sku(tenant_a):
    form, _ = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})
    substance, _ = ActiveSubstance.all_objects.get_or_create(tenant=tenant_a, code="PAR", defaults={"canonical_name": "Paracetamol"})
    cmp, _ = ClinicalMedicinalProduct.all_objects.get_or_create(tenant=tenant_a, canonical_name="Paracetamol 500mg Tablet", defaults={"dose_form": form})
    mmp, _ = ManufacturedMedicinalProduct.all_objects.get_or_create(tenant=tenant_a, code="MMP1", brand_name="Test Pharma", defaults={"clinical_product": cmp})
    pkg, _ = PackageDefinition.objects.get_or_create(code="BOX-100", defaults={"description": "Box of 100", "unit_of_measure": "tablet"})
    sku_obj, _ = CommercialSKU.all_objects.get_or_create(tenant=tenant_a, sku_code="SKU-PAR-100", defaults={"manufactured_product": mmp, "package_definition": pkg, "display_name": "Paracetamol 500mg x 100"})
    return sku_obj

@pytest.fixture
def manufactured_product(sku):
    return sku.manufactured_product

@pytest.fixture
def inventory_location(tenant_a, branch):
    return InventoryLocation.objects.create(
        tenant=tenant_a,
        branch=branch,
        location_code="MAIN-STORE",
        name="Main Store",
        location_type=InventoryLocation.LocationType.STORE,
    )

@pytest.fixture
def inventory_location_quarantine(tenant_a, branch):
    return InventoryLocation.objects.create(
        tenant=tenant_a,
        branch=branch,
        location_code="QUAR-01",
        name="Quarantine Zone",
        location_type=InventoryLocation.LocationType.QUARANTINE,
        quarantine_capability=True,
    )

@pytest.fixture
def inventory_batch(tenant_a, sku, manufactured_product):
    return InventoryBatch.objects.create(
        tenant=tenant_a,
        sku=sku,
        manufactured_product=manufactured_product,
        manufacturer_batch_number="BATCH-X1",
        expiry_date=timezone.now().date() + timezone.timedelta(days=365)
    )
