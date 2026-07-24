import uuid

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.tenant_context import set_current_tenant_id
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry, InventoryLocation
from apps.inventory.services import InventoryLedgerService
from apps.medicines.models import CommercialSKU
from apps.organizations.models import Location
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Seeds initial inventory data for testing."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=str, help="Tenant slug")

    def handle(self, *args, **options):
        tenant_slug = options.get("tenant")
        
        tenants = Tenant.objects.all()
        if tenant_slug:
            tenants = tenants.filter(slug=tenant_slug)
            
        if not tenants.exists():
            self.stderr.write("No tenants found.")
            return

        for tenant in tenants:
            set_current_tenant_id(tenant.id)
            self.stdout.write(f"Seeding inventory for tenant {tenant.name}...")
            
            with transaction.atomic():
                # Get or create a branch
                branch = Location.objects.filter(tenant=tenant).first()
                if not branch:
                    branch = Location.objects.create(tenant=tenant, name=f"Main Branch - {tenant.name}")
                    
                # Get or create a location
                location, _ = InventoryLocation.objects.get_or_create(
                    tenant=tenant,
                    branch=branch,
                    location_code="MAIN",
                    defaults={
                        "name": "Main Store",
                        "status": InventoryLocation.Status.ACTIVE,
                        "location_type": InventoryLocation.LocationType.STORE,
                    }
                )
                
                # Get a SKU
                sku = CommercialSKU.objects.filter(tenant=tenant).first()
                if not sku:
                    self.stderr.write(f"No SKUs found for tenant {tenant.name}. Skipping.")
                    continue
                    
                # Create an inventory batch
                batch, _ = InventoryBatch.objects.get_or_create(
                    tenant=tenant,
                    sku=sku,
                    manufacturer_batch_number="SEED-BATCH-001",
                    defaults={
                        "manufacture_date": "2023-01-01",
                        "expiry_date": "2025-01-01",
                        "quality_status": InventoryBatch.QualityStatus.RELEASED,
                        "manufactured_product": sku.manufactured_product,
                    }
                )
                
                # Post an entry
                # Check if seed entry already exists
                if not InventoryLedgerEntry.objects.filter(source_document_id="SEED-001").exists():
                    InventoryLedgerService.post_entry(
                        tenant=tenant,
                        branch=branch,
                        location=location,
                        inventory_batch=batch,
                        sku=sku,
                        entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
                        quantity_delta=1000,
                        unit="tablet",
                        base_quantity_delta=1000,
                        effective_timestamp="2023-01-01T00:00:00Z",
                        source_document_type="Migration",
                        source_document_id="SEED-001",
                        idempotency_key=str(uuid.uuid4())
                    )
                    self.stdout.write(f"Seeded 1000 units of {sku.sku_code} for tenant {tenant.name}.")
                else:
                    self.stdout.write(f"Seed entry already exists for tenant {tenant.name}.")
                    
        set_current_tenant_id(None)
        self.stdout.write(self.style.SUCCESS("Inventory seeding complete."))
