from django.utils import timezone

class StockTransferService:
    @staticmethod
    @transaction.atomic
    def request_transfer(*, tenant, transfer_number, source_branch, dest_branch, source_location, dest_location, requested_by, lines_data):
        if source_location.branch != source_branch or dest_location.branch != dest_branch:
            raise ValidationError("Locations must belong to their respective branches.")
            
        transfer = StockTransfer.objects.create(
            tenant=tenant,
            transfer_number=transfer_number,
            source_branch=source_branch,
            destination_branch=dest_branch,
            source_location=source_location,
            destination_location=dest_location,
            requested_by=requested_by,
            status=StockTransfer.Status.SUBMITTED,
        )
        
        for line in lines_data:
            sku = line["sku"]
            qty = line["quantity"]
            StockTransferLine.objects.create(
                tenant=tenant,
                transfer=transfer,
                sku=sku,
                requested_quantity=qty,
                unit=sku.package_definition.unit_of_measure,
            )
            
        emit_event(tenant_id=str(tenant.pk), aggregate_type="StockTransfer", aggregate_id=str(transfer.pk), event_type="StockTransferCreated", payload={"transfer_number": transfer_number})
        return transfer

    @staticmethod
    @transaction.atomic
    def approve_transfer(*, transfer, approver):
        if transfer.status != StockTransfer.Status.SUBMITTED:
            raise ValidationError("Only submitted transfers can be approved.")
        transfer.status = StockTransfer.Status.APPROVED
        transfer.approved_by = approver
        transfer.save()
        emit_event(tenant_id=str(transfer.tenant.pk), aggregate_type="StockTransfer", aggregate_id=str(transfer.pk), event_type="StockTransferApproved", payload={})
        return transfer
        
    @staticmethod
    @transaction.atomic
    def allocate_and_dispatch(*, transfer, dispatcher):
        if transfer.status != StockTransfer.Status.APPROVED:
            raise ValidationError("Only approved transfers can be dispatched.")
            
        # Allocate FEFO and dispatch
        for line in transfer.lines.all():
            allocations = FEFOAllocationService.allocate_stock(
                tenant=transfer.tenant,
                branch=transfer.source_branch,
                location=transfer.source_location,
                sku=line.sku,
                required_quantity=line.requested_quantity
            )
            
            # Post TRANSFER_OUT for each allocation
            for batch, qty in allocations:
                InventoryLedgerService.post_entry(
                    tenant=transfer.tenant,
                    branch=transfer.source_branch,
                    location=transfer.source_location,
                    sku=line.sku,
                    inventory_batch=batch,
                    entry_type=InventoryLedgerEntry.EntryType.TRANSFER_OUT,
                    quantity_delta=-qty,
                    unit=line.unit,
                    base_quantity_delta=-qty,
                    effective_timestamp=timezone.now(),
                    source_document_type="STOCK_TRANSFER",
                    source_document_id=str(transfer.pk),
                    source_line_id=str(line.pk),
                    idempotency_key=f"dispatch-{transfer.pk}-{line.pk}-{batch.pk}",
                    actor=dispatcher,
                    reason_code="TRANSFER_DISPATCH",
                )
                line.allocated_quantity += qty
                line.dispatched_quantity += qty
            line.save()
            
        transfer.status = StockTransfer.Status.DISPATCHED
        transfer.dispatched_by = dispatcher
        transfer.dispatch_timestamp = timezone.now()
        transfer.save()
        
        emit_event(tenant_id=str(transfer.tenant.pk), aggregate_type="StockTransfer", aggregate_id=str(transfer.pk), event_type="StockTransferDispatched", payload={})
        return transfer
        
    @staticmethod
    @transaction.atomic
    def receive_transfer(*, transfer, receiver, received_lines_data):
        if transfer.status not in [StockTransfer.Status.DISPATCHED, StockTransfer.Status.IN_TRANSIT, StockTransfer.Status.PARTIALLY_RECEIVED]:
            raise ValidationError("Transfer is not in a receivable state.")
            
        # receive_lines_data: list of dicts: {"line_id": str, "batch_id": str, "quantity": decimal, "damaged": decimal}
        # In a real implementation, we map this directly against dispatched ledger lines.
        # For simplicity, we assume received_lines_data perfectly maps to what was dispatched.
        for data in received_lines_data:
            line = transfer.lines.get(pk=data["line_id"])
            batch = InventoryBatch.objects.get(pk=data["batch_id"])
            qty = data["quantity"]
            damaged = data.get("damaged", 0)
            
            if qty > 0:
                InventoryLedgerService.post_entry(
                    tenant=transfer.tenant,
                    branch=transfer.destination_branch,
                    location=transfer.destination_location,
                    sku=line.sku,
                    inventory_batch=batch,
                    entry_type=InventoryLedgerEntry.EntryType.TRANSFER_IN,
                    quantity_delta=qty,
                    unit=line.unit,
                    base_quantity_delta=qty,
                    effective_timestamp=timezone.now(),
                    source_document_type="STOCK_TRANSFER",
                    source_document_id=str(transfer.pk),
                    source_line_id=str(line.pk),
                    idempotency_key=f"receive-{transfer.pk}-{line.pk}-{batch.pk}-{uuid.uuid4()}",
                    actor=receiver,
                    reason_code="TRANSFER_RECEIPT",
                )
                line.received_quantity += qty
                
            if damaged > 0:
                # Post direct to a damaged location if available, or just record it and leave it in transit/loss
                pass
                
            line.save()
            
        transfer.status = StockTransfer.Status.RECEIVED
        transfer.received_by = receiver
        transfer.receipt_timestamp = timezone.now()
        transfer.save()
        
        emit_event(tenant_id=str(transfer.tenant.pk), aggregate_type="StockTransfer", aggregate_id=str(transfer.pk), event_type="StockTransferReceived", payload={})
        return transfer

class InventoryAdjustmentService:
    @staticmethod
    @transaction.atomic
    def request_adjustment(*, tenant, branch, location, sku, batch, delta, reason, actor, idempotency_key):
        entry_type = InventoryLedgerEntry.EntryType.ADJUSTMENT_INCREASE if delta > 0 else InventoryLedgerEntry.EntryType.ADJUSTMENT_DECREASE
        
        entry = InventoryLedgerService.post_entry(
            tenant=tenant,
            branch=branch,
            location=location,
            sku=sku,
            inventory_batch=batch,
            entry_type=entry_type,
            quantity_delta=delta,
            unit=sku.package_definition.unit_of_measure,
            base_quantity_delta=delta,
            effective_timestamp=timezone.now(),
            source_document_type="MANUAL_ADJUSTMENT",
            source_document_id=idempotency_key, # Using idempotency key as ID for simple adjustments
            idempotency_key=idempotency_key,
            actor=actor,
            reason_code=reason,
        )
        
        emit_event(tenant_id=str(tenant.pk), aggregate_type="InventoryAdjustment", aggregate_id=str(entry.pk), event_type="InventoryAdjustmentPosted", payload={"delta": str(delta)})
        return entry

class StocktakeService:
    @staticmethod
    @transaction.atomic
    def open_stocktake(*, tenant, branch, locations, scope, creator):
        session = StocktakeSession.objects.create(
            tenant=tenant,
            branch=branch,
            scope=scope,
            status=StocktakeSession.Status.OPEN,
            created_by=creator,
            start_time=timezone.now(),
        )
        session.locations.set(locations)
        emit_event(tenant_id=str(tenant.pk), aggregate_type="StocktakeSession", aggregate_id=str(session.pk), event_type="StocktakeOpened", payload={})
        return session

    @staticmethod
    @transaction.atomic
    def record_count(*, session, location, sku, batch, counted_quantity, counter):
        if session.status != StocktakeSession.Status.OPEN:
            raise ValidationError("Stocktake is not open.")
            
        balance = InventoryBalanceService.get_balance(tenant=session.tenant, branch=session.branch, location=location, sku=sku, inventory_batch=batch)
        expected = balance.on_hand
        
        count = StocktakeCount.objects.create(
            tenant=session.tenant,
            session=session,
            location=location,
            sku=sku,
            batch=batch,
            expected_quantity=expected,
            counted_quantity=counted_quantity,
            variance=counted_quantity - expected,
            counter=counter,
            timestamp=timezone.now()
        )
        return count

    @staticmethod
    @transaction.atomic
    def post_variances(*, session, approver):
        if session.status != StocktakeSession.Status.OPEN:
            raise ValidationError("Stocktake must be open to post variances.")
            
        for count in session.counts.all():
            if count.variance != 0:
                entry_type = InventoryLedgerEntry.EntryType.STOCKTAKE_GAIN if count.variance > 0 else InventoryLedgerEntry.EntryType.STOCKTAKE_LOSS
                InventoryLedgerService.post_entry(
                    tenant=session.tenant,
                    branch=session.branch,
                    location=count.location,
                    sku=count.sku,
                    inventory_batch=count.batch,
                    entry_type=entry_type,
                    quantity_delta=count.variance,
                    unit=count.sku.package_definition.unit_of_measure,
                    base_quantity_delta=count.variance,
                    effective_timestamp=timezone.now(),
                    source_document_type="STOCKTAKE",
                    source_document_id=str(session.pk),
                    source_line_id=str(count.pk),
                    idempotency_key=f"stocktake-{session.pk}-{count.pk}",
                    actor=approver,
                    reason_code="STOCKTAKE_POSTING",
                )
                
        session.status = StocktakeSession.Status.POSTED
        session.approved_by = approver
        session.end_time = timezone.now()
        session.save()
        emit_event(tenant_id=str(session.tenant.pk), aggregate_type="StocktakeSession", aggregate_id=str(session.pk), event_type="StocktakeVariancePosted", payload={})
        return session
