import sys
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.tenant_context import set_current_tenant_id
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, InventoryReservation
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Checks the integrity of the inventory ledger and balance projections."

    def add_arguments(self, parser):
        parser.add_argument("--repair-projections", action="store_true", help="Repair balance projections if corrupted.")
        parser.add_argument("--tenant-id", type=str, help="Run only for a specific tenant.")

    def handle(self, *args, **options):
        repair = options["repair_projections"]
        tenant_id_arg = options["tenant_id"]

        if tenant_id_arg:
            tenants = Tenant.objects.filter(id=tenant_id_arg)
        else:
            tenants = Tenant.objects.all()

        total_issues = 0
        repaired_count = 0

        for tenant in tenants:
            set_current_tenant_id(tenant.id)
            self.stdout.write(f"Checking tenant {tenant.name} ({tenant.id})...")

            # 1. Negative Balances
            negative_balances = InventoryBalance.objects.filter(on_hand__lt=0) | InventoryBalance.objects.filter(available__lt=0)
            for b in negative_balances:
                self.stderr.write(f"[WARNING] Tenant {tenant.id} has negative balance on {b.sku.sku_code} at {b.location.location_code}")
                total_issues += 1

            # 2. Check for missing batches
            orphan_entries = InventoryLedgerEntry.objects.filter(inventory_batch__isnull=True).exclude(entry_type=InventoryLedgerEntry.EntryType.RECEIPT)
            if orphan_entries.exists():
                self.stderr.write(f"[WARNING] Tenant {tenant.id} has {orphan_entries.count()} ledger entries without a batch.")
                total_issues += orphan_entries.count()

            # 3. Projection Mismatch (Sum of ledger entries != Balance)
            all_balances = InventoryBalance.objects.all()
            for balance in all_balances:
                # Sum ledger entries
                ledger_sum = Decimal('0.0000')
                entries = InventoryLedgerEntry.objects.filter(
                    sku=balance.sku,
                    location=balance.location,
                    inventory_batch=balance.inventory_batch
                )
                for entry in entries:
                    ledger_sum += entry.base_quantity_delta

                if balance.on_hand != ledger_sum:
                    self.stderr.write(f"[ERROR] Projection mismatch for {balance.sku.sku_code} at {balance.location.location_code}. "
                                      f"Expected: {ledger_sum}, Got: {balance.on_hand}")
                    total_issues += 1

                    if repair:
                        with transaction.atomic():
                            self.stdout.write(f"Repairing balance {balance.id}...")
                            balance.on_hand = ledger_sum
                            # Re-derive availability based on location capability/status
                            if balance.location.quarantine_capability or balance.location.damaged_goods_capability or balance.location.expiry_hold_capability or balance.quality_status == "EXPIRED":
                                balance.available = Decimal('0.0000')
                            else:
                                balance.available = balance.on_hand - balance.reserved
                            balance.save()
                            repaired_count += 1

            # 4. Reservation Mismatch
            for balance in all_balances:
                active_reservations = InventoryReservation.objects.filter(
                    sku=balance.sku,
                    source_location=balance.location,
                    batch=balance.inventory_batch,
                    status__in=[InventoryReservation.Status.ALLOCATED, InventoryReservation.Status.PARTIALLY_FULFILLED]
                )
                res_sum = Decimal('0.0000')
                for res in active_reservations:
                    res_sum += res.allocated_quantity
                
                if balance.reserved != res_sum:
                    self.stderr.write(f"[ERROR] Reservation mismatch for {balance.sku.sku_code}. "
                                      f"Expected: {res_sum}, Got: {balance.reserved}")
                    total_issues += 1
                    
                    if repair:
                        with transaction.atomic():
                            self.stdout.write(f"Repairing reservation on balance {balance.id}...")
                            balance.reserved = res_sum
                            if balance.location.quarantine_capability or balance.location.damaged_goods_capability or balance.location.expiry_hold_capability or balance.quality_status == "EXPIRED":
                                balance.available = Decimal('0.0000')
                            else:
                                balance.available = balance.on_hand - balance.reserved
                            balance.save()
                            repaired_count += 1

        set_current_tenant_id(None)

        self.stdout.write(f"Integrity check complete. Total issues found: {total_issues}")
        if repair:
            self.stdout.write(f"Repaired {repaired_count} projections.")

        if total_issues > 0 and not repair:
            sys.exit(1)
