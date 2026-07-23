import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dawatrace.settings.test')
django.setup()

from django.core.management import call_command
call_command('migrate', verbosity=0)

from apps.inventory.models import *
from apps.inventory.services import *
from apps.medicines.models import *
from apps.organizations.models import *
from apps.tenancy.models import *
from django.utils import timezone
import datetime

tenant = Tenant.objects.create(name="Debug Tenant", slug="debug")
org = Organization.all_objects.create(tenant=tenant, name="Org", code="ORG", organization_type="PHARMACY")
branch = Location.all_objects.create(tenant=tenant, organization=org, name="Branch", code="BRN")
inv_loc = InventoryLocation.objects.create(tenant=tenant, branch=branch, location_code="BRN-STORE", location_type=InventoryLocation.LocationType.STORE)

form, _ = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})
cmp = ClinicalMedicinalProduct.all_objects.create(tenant=tenant, canonical_name="C", dose_form=form)
mmp = ManufacturedMedicinalProduct.all_objects.create(tenant=tenant, code="M", brand_name="M", clinical_product=cmp)
pkg, _ = PackageDefinition.objects.get_or_create(code="B", defaults={"unit_of_measure": "tab"})
sku = CommercialSKU.all_objects.create(tenant=tenant, sku_code="S", manufactured_product=mmp, package_definition=pkg, display_name="S")
batch = InventoryBatch.objects.create(tenant=tenant, sku=sku, manufactured_product=mmp, manufacturer_batch_number="X", expiry_date=timezone.now().date() + datetime.timedelta(days=30))

print("Before post_entry, balances:", list(InventoryBalance.objects.all()))
try:
    entry = InventoryLedgerService.post_entry(
        tenant=tenant, branch=branch, location=inv_loc, sku=sku, inventory_batch=batch,
        entry_type=InventoryLedgerEntry.EntryType.RECEIPT, quantity_delta=100, unit="box", base_quantity_delta=100,
        effective_timestamp=timezone.now(), source_document_type="TEST", source_document_id="1", idempotency_key="r1"
    )
    print("After post_entry, balances:", list(InventoryBalance.objects.all()))
except Exception as e:
    import traceback
    traceback.print_exc()

