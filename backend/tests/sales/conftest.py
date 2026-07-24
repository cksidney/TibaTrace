from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.tenant_context import set_current_tenant_id
from apps.customers.models import Customer, CustomerCommercialProfile, CustomerDeliveryAddress
from apps.identity.models import User
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry, InventoryLocation
from apps.inventory.services import InventoryLedgerService
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization


@pytest.fixture(autouse=True)
def enable_tenant_context(tenant_a):
    set_current_tenant_id(tenant_a.id)
    yield
    set_current_tenant_id(None)


@pytest.fixture
def test_user(tenant_a):
    return User.objects.create_user(
        username="sales_admin_user",
        email="sales_admin@example.com",
        password="password123",
        tenant=tenant_a,
    )


@pytest.fixture
def verifier_user(tenant_a):
    return User.objects.create_user(
        username="sales_verifier_user",
        email="sales.verifier@example.com",
        password="password123",
        tenant=tenant_a,
    )


@pytest.fixture
def active_customer(tenant_a, test_user):
    c = Customer.objects.create(
        tenant=tenant_a,
        customer_number="CUST-SALES-01",
        legal_name="Sales Corp",
        customer_type=Customer.CustomerType.RETAIL,
        status=Customer.Status.ACTIVE,
        created_by=test_user,
    )
    CustomerCommercialProfile.objects.create(tenant=tenant_a, customer=c)
    return c


@pytest.fixture
def delivery_address(tenant_a, active_customer):
    return CustomerDeliveryAddress.objects.create(
        tenant=tenant_a,
        customer=active_customer,
        address_code="MAIN-ADDR",
        recipient_name="Sales HQ",
        address_line1="123 Market St",
        city="Nairobi",
        country="Kenya",
    )


@pytest.fixture
def branch(tenant_a):
    org, _ = Organization.all_objects.get_or_create(
        tenant=tenant_a, code="ORG-TEST", defaults={"name": "Test Org", "organization_type": "PHARMACY"}
    )
    loc, _ = Location.all_objects.get_or_create(
        tenant=tenant_a, organization=org, code="MAIN", defaults={"name": "Main Dispensary"}
    )
    return loc


@pytest.fixture
def sku(tenant_a):
    form, _ = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})
    substance, _ = ActiveSubstance.all_objects.get_or_create(
        tenant=tenant_a, code="PAR", defaults={"canonical_name": "Paracetamol"}
    )
    cmp, _ = ClinicalMedicinalProduct.all_objects.get_or_create(
        tenant=tenant_a, canonical_name="Paracetamol 500mg Tablet", defaults={"dose_form": form}
    )
    mmp, _ = ManufacturedMedicinalProduct.all_objects.get_or_create(
        tenant=tenant_a, code="MMP1", brand_name="Test Pharma", defaults={"clinical_product": cmp}
    )
    pkg, _ = PackageDefinition.objects.get_or_create(
        code="BOX-100", defaults={"description": "Box of 100", "unit_of_measure": "tablet"}
    )
    sku_obj, _ = CommercialSKU.all_objects.get_or_create(
        tenant=tenant_a,
        sku_code="SKU-PAR-100",
        defaults={
            "manufactured_product": mmp,
            "package_definition": pkg,
            "display_name": "Paracetamol 500mg x 100",
            "status": CommercialSKU.STATUS_ACTIVE,
        },
    )
    if sku_obj.status != CommercialSKU.STATUS_ACTIVE:
        sku_obj.status = CommercialSKU.STATUS_ACTIVE
        sku_obj.save(update_fields=["status", "updated_at"])
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
def inventory_batch(tenant_a, sku, manufactured_product):
    return InventoryBatch.objects.create(
        tenant=tenant_a,
        sku=sku,
        manufactured_product=manufactured_product,
        manufacturer_batch_number="BATCH-001",
        expiry_date="2030-12-31",
        quality_status=InventoryBatch.QualityStatus.RELEASED,
    )


@pytest.fixture
def stocked_inventory(
    tenant_a,
    branch,
    inventory_location,
    inventory_batch,
    sku,
    test_user,
):
    InventoryLedgerService.post_entry(
        tenant=tenant_a,
        branch=branch,
        location=inventory_location,
        sku=sku,
        inventory_batch=inventory_batch,
        entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
        quantity_delta=Decimal("100"),
        unit="EA",
        base_quantity_delta=Decimal("100"),
        effective_timestamp=timezone.now(),
        source_document_type="TEST_RECEIPT",
        source_document_id=str(inventory_batch.pk),
        idempotency_key=f"TEST_RECEIPT_{inventory_batch.pk}",
        actor=test_user,
    )
    return inventory_location, inventory_batch
