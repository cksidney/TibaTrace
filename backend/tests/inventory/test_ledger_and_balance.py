import pytest
from django.utils import timezone

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry
from apps.inventory.services import InventoryBalanceService, InventoryLedgerService


@pytest.mark.django_db
class TestInventoryLedgerAndBalance:
    def test_post_receipt_updates_balance(self, tenant_a, branch, inventory_location, sku, inventory_batch):
        entry = InventoryLedgerService.post_entry(
            tenant=tenant_a,
            branch=branch,
            location=inventory_location,
            sku=sku,
            inventory_batch=inventory_batch,
            entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
            quantity_delta=100,
            unit="box",
            base_quantity_delta=100,
            effective_timestamp=timezone.now(),
            source_document_type="TEST",
            source_document_id="123",
            idempotency_key="receipt-1",
        )
        
        assert entry.pk is not None
        
        balance = InventoryBalance.all_objects.get(
            tenant=tenant_a, location=inventory_location, sku=sku, inventory_batch=inventory_batch
        )
        assert balance.on_hand == 100
        assert balance.available == 100

    def test_rebuild_balances(self, tenant_a, branch, inventory_location, sku, inventory_batch):
        InventoryLedgerService.post_entry(
            tenant=tenant_a, branch=branch, location=inventory_location, sku=sku,
            inventory_batch=inventory_batch, entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
            quantity_delta=50, unit="box", base_quantity_delta=50,
            effective_timestamp=timezone.now(), source_document_type="TEST",
            source_document_id="1", idempotency_key="test-1"
        )
        
        InventoryLedgerService.post_entry(
            tenant=tenant_a, branch=branch, location=inventory_location, sku=sku,
            inventory_batch=inventory_batch, entry_type=InventoryLedgerEntry.EntryType.ISSUE,
            quantity_delta=-10, unit="box", base_quantity_delta=-10,
            effective_timestamp=timezone.now(), source_document_type="TEST",
            source_document_id="2", idempotency_key="test-2"
        )
        
        InventoryBalanceService.rebuild_all_balances(tenant_a)
        
        balance = InventoryBalance.all_objects.get(tenant=tenant_a, sku=sku)
        assert balance.on_hand == 40
        assert balance.available == 40
