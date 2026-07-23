import pytest
from django.utils import timezone

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry
from apps.inventory.services import ExpiryControlService, InventoryLedgerService, StocktakeService


@pytest.mark.django_db
class TestStocktakeAndExpiry:
    def test_stocktake_posts_variance(self, tenant_a, branch, inventory_location, sku, inventory_batch, admin_user):
        InventoryLedgerService.post_entry(
            tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, inventory_batch=inventory_batch,
            entry_type=InventoryLedgerEntry.EntryType.RECEIPT, quantity_delta=100, unit="box", base_quantity_delta=100,
            effective_timestamp=timezone.now(), source_document_type="TEST", source_document_id="1", idempotency_key="r1"
        )
        
        session = StocktakeService.open_stocktake(tenant=tenant_a, branch=branch, locations=[inventory_location], scope="FULL", creator=admin_user)
        
        StocktakeService.record_count(session=session, location=inventory_location, sku=sku, batch=inventory_batch, counted_quantity=95, counter=admin_user)
        
        StocktakeService.post_variances(session=session, approver=admin_user)
        
        balance = InventoryBalance.all_objects.get(tenant=tenant_a, sku=sku)
        assert balance.on_hand == 95
        
    def test_expiry_control(self, tenant_a, branch, inventory_location, sku, inventory_batch, admin_user):
        InventoryLedgerService.post_entry(
            tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, inventory_batch=inventory_batch,
            entry_type=InventoryLedgerEntry.EntryType.RECEIPT, quantity_delta=100, unit="box", base_quantity_delta=100,
            effective_timestamp=timezone.now(), source_document_type="TEST", source_document_id="1", idempotency_key="r1"
        )
        
        # force expiry
        inventory_batch.expiry_date = timezone.now().date() - timezone.timedelta(days=1)
        inventory_batch.save()
        
        ExpiryControlService.process_expired_batches(tenant_a)
        
        balance = InventoryBalance.all_objects.get(tenant=tenant_a, sku=sku, inventory_batch=inventory_batch)
        assert balance.on_hand == 100
        assert balance.available == 0
        assert balance.expired == 100
