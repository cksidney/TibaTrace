class InventoryReceiptService:
    @staticmethod
    @transaction.atomic
    def post_receipt(*, tenant, received_batch, receiving_location, actor=None):
        if received_batch.quality_status != "RELEASED":
            raise ValidationError("Only RELEASED batches can be posted to inventory.")
            
        # Ensure we haven't already posted this batch to avoid duplicates
        if InventoryBatch.all_objects.filter(tenant=tenant, source_received_batch=received_batch).exists():
            raise ValidationError("This batch has already been posted to inventory.")
            
        # Create the inventory batch representation
        inv_batch = InventoryBatch.objects.create(
            tenant=tenant,
            sku=received_batch.goods_receipt_line.sku,
            manufactured_product=received_batch.goods_receipt_line.sku.manufactured_product,
            source_received_batch=received_batch,
            manufacturer_batch_number=received_batch.manufacturer_batch_number,
            manufacture_date=received_batch.manufacture_date,
            expiry_date=received_batch.expiry_date,
            quality_status=InventoryBatch.QualityStatus.RELEASED,
        )
        
        # Post to ledger
        qty = received_batch.received_quantity
        unit = received_batch.goods_receipt_line.sku.package_definition.unit_of_measure
        
        entry = InventoryLedgerService.post_entry(
            tenant=tenant,
            branch=receiving_location.branch,
            location=receiving_location,
            sku=inv_batch.sku,
            inventory_batch=inv_batch,
            entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
            quantity_delta=qty,
            unit=unit,
            base_quantity_delta=qty,
            effective_timestamp=received_batch.created_at,
            source_document_type="RECEIVED_BATCH",
            source_document_id=str(received_batch.pk),
            idempotency_key=f"receipt-post-{received_batch.pk}",
            actor=actor,
            reason_code="PROCUREMENT_RECEIPT",
        )
        
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="InventoryBatch",
            aggregate_id=str(inv_batch.pk),
            event_type="InventoryReceiptPosted",
            payload={"sku_id": str(inv_batch.sku.pk), "quantity": str(qty)},
        )
        
        return inv_batch
