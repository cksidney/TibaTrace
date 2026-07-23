class ExpiryControlService:
    @staticmethod
    @transaction.atomic
    def process_expired_batches(tenant):
        """
        Find batches that are past their expiry date and move them to EXPIRED quality status.
        Update ledger to reflect the status change.
        """
        expired_batches = InventoryBatch.objects.filter(
            tenant=tenant,
            quality_status__in=[InventoryBatch.QualityStatus.RELEASED, InventoryBatch.QualityStatus.QUARANTINED],
            expiry_date__lt=timezone.now().date()
        )
        
        for batch in expired_batches:
            batch.quality_status = InventoryBatch.QualityStatus.EXPIRED
            batch.save()
            
            # Re-evaluate all balances for this batch so they update availability
            balances = InventoryBalance.objects.filter(tenant=tenant, inventory_batch=batch)
            for balance in balances:
                InventoryBalanceService.apply_ledger_entry(
                    InventoryLedgerEntry(
                        tenant=tenant, 
                        branch=balance.branch, 
                        location=balance.location, 
                        sku=balance.sku, 
                        inventory_batch=batch,
                        entry_type=InventoryLedgerEntry.EntryType.EXPIRY,
                        base_quantity_delta=0 # We use apply_ledger_entry just to trigger availability recalc
                    )
                )

class RecallInventoryService:
    @staticmethod
    @transaction.atomic
    def initiate_recall(*, tenant, manufacturer_batch_number, sku=None):
        query = {"tenant": tenant, "manufacturer_batch_number": manufacturer_batch_number}
        if sku:
            query["sku"] = sku
            
        batches = InventoryBatch.objects.filter(**query)
        for batch in batches:
            batch.recall_status = InventoryBatch.RecallStatus.RECALLED
            batch.save()
            
            balances = InventoryBalance.objects.filter(tenant=tenant, inventory_batch=batch)
            for balance in balances:
                # Trigger availability recalculation
                InventoryBalanceService.apply_ledger_entry(
                    InventoryLedgerEntry(
                        tenant=tenant, 
                        branch=balance.branch, 
                        location=balance.location, 
                        sku=balance.sku, 
                        inventory_batch=batch,
                        entry_type=InventoryLedgerEntry.EntryType.RECALL_HOLD,
                        base_quantity_delta=0
                    )
                )
