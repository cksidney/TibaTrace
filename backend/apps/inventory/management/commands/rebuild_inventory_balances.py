import time

from django.core.management.base import BaseCommand

from apps.inventory.services import InventoryBalanceService
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Rebuilds all inventory balance projections from the immutable ledger."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=str, help="Tenant slug to scope rebuild")
        parser.add_argument("--dry-run", action="store_true", help="Safe dry-run mode")

    def handle(self, *args, **options):
        tenant_slug = options.get("tenant")
        dry_run = options.get("dry_run")
        
        tenants = Tenant.objects.all()
        if tenant_slug:
            tenants = tenants.filter(slug=tenant_slug)
            
        if dry_run:
            self.stdout.write(self.style.WARNING("Running in DRY-RUN mode. No changes will be saved."))
            
        start_time = time.time()
        count = 0
        
        for tenant in tenants:
            self.stdout.write(f"Rebuilding balances for tenant: {tenant.name}...")
            if not dry_run:
                InventoryBalanceService.rebuild_all_balances(tenant)
                count += 1
                
        duration = time.time() - start_time
        
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Successfully rebuilt balances for {count} tenants in {duration:.2f}s."))
        else:
            self.stdout.write(self.style.SUCCESS("Dry run completed."))
