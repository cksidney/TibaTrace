import datetime

import pytest
from django.utils import timezone

from apps.inventory.models import InventoryBalance, InventoryBatch, InventoryLedgerEntry
from apps.inventory.services import FEFOAllocationService, InventoryLedgerService, InventoryReservationService


@pytest.mark.django_db
class TestFEFOAllocation:
    def test_fefo_allocation(self, tenant_a, branch, inventory_location, sku, manufactured_product):
        # Create two batches with different expiry
        batch_near = InventoryBatch.objects.create(
            tenant=tenant_a, sku=sku, manufactured_product=manufactured_product,
            manufacturer_batch_number="NEAR", expiry_date=timezone.now().date() + datetime.timedelta(days=30)
        )
        batch_far = InventoryBatch.objects.create(
            tenant=tenant_a, sku=sku, manufactured_product=manufactured_product,
            manufacturer_batch_number="FAR", expiry_date=timezone.now().date() + datetime.timedelta(days=180)
        )
        
        # Post receipts
        InventoryLedgerService.post_entry(
            tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, inventory_batch=batch_far,
            entry_type=InventoryLedgerEntry.EntryType.RECEIPT, quantity_delta=100, unit="box", base_quantity_delta=100,
            effective_timestamp=timezone.now(), source_document_type="TEST", source_document_id="1", idempotency_key="r1"
        )
        InventoryLedgerService.post_entry(
            tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, inventory_batch=batch_near,
            entry_type=InventoryLedgerEntry.EntryType.RECEIPT, quantity_delta=50, unit="box", base_quantity_delta=50,
            effective_timestamp=timezone.now(), source_document_type="TEST", source_document_id="2", idempotency_key="r2"
        )
        
        allocations = FEFOAllocationService.allocate_stock(
            tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, required_quantity=80
        )
        
        assert len(allocations) == 2
        assert allocations[0][0] == batch_near
        assert allocations[0][1] == 50
        assert allocations[1][0] == batch_far
        assert allocations[1][1] == 30

    def test_reservation_reduces_availability(self, tenant_a, branch, inventory_location, sku, inventory_batch, admin_user):
        InventoryLedgerService.post_entry(
            tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, inventory_batch=inventory_batch,
            entry_type=InventoryLedgerEntry.EntryType.RECEIPT, quantity_delta=100, unit="box", base_quantity_delta=100,
            effective_timestamp=timezone.now(), source_document_type="TEST", source_document_id="1", idempotency_key="r1"
        )
        
        InventoryReservationService.reserve_stock(
            tenant=tenant_a, branch=branch, source_location=inventory_location, sku=sku,
            requested_quantity=40, purpose="SALES", actor=admin_user, idempotency_key="res1"
        )
        
        balance = InventoryBalance.all_objects.get(tenant=tenant_a, sku=sku)
        assert balance.on_hand == 100
        assert balance.reserved == 40
        assert balance.available == 60
