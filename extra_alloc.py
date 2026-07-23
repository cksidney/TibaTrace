class FEFOAllocationService:
    """
    Implements First-Expire-First-Out allocation logic.
    """
    @staticmethod
    def allocate_stock(*, tenant, branch, location=None, sku, required_quantity, exclude_batches=None):
        """
        Returns a list of tuples: (InventoryBatch, allocated_quantity)
        satisfying the required_quantity via FEFO.
        """
        exclude_batches = exclude_batches or []
        
        # Query balances that are available
        balances = InventoryBalance.objects.filter(
            tenant=tenant,
            branch=branch,
            sku=sku,
            available__gt=0
        ).exclude(
            inventory_batch__in=exclude_batches
        )
        
        if location:
            balances = balances.filter(location=location)
            
        # Tie-breakers: expiry_date ASC, batch_id ASC
        # Note: inventory_batch__expiry_date is derived from the relation
        balances = balances.select_related("inventory_batch").order_by(
            "inventory_batch__expiry_date", 
            "inventory_batch__id"
        )
        
        allocations = []
        remaining_quantity = required_quantity
        
        for balance in balances:
            if remaining_quantity <= 0:
                break
                
            qty_to_take = min(balance.available, remaining_quantity)
            allocations.append((balance.inventory_batch, qty_to_take))
            remaining_quantity -= qty_to_take
            
        if remaining_quantity > 0:
            raise ValidationError(f"Insufficient eligible stock. Short by {remaining_quantity} {sku.package_definition.unit_of_measure}.")
            
        return allocations

class InventoryReservationService:
    @staticmethod
    @transaction.atomic
    def reserve_stock(*, tenant, branch, source_location, sku, requested_quantity, purpose, actor, idempotency_key, expiry_time=None):
        if InventoryReservation.all_objects.filter(tenant=tenant, idempotency_key=idempotency_key).exists():
            return InventoryReservation.all_objects.get(tenant=tenant, idempotency_key=idempotency_key)
            
        # First, try to allocate FEFO
        allocations = FEFOAllocationService.allocate_stock(
            tenant=tenant, 
            branch=branch, 
            location=source_location, 
            sku=sku, 
            required_quantity=requested_quantity
        )
        
        reservation = InventoryReservation.objects.create(
            tenant=tenant,
            branch=branch,
            source_location=source_location,
            sku=sku,
            requested_quantity=requested_quantity,
            allocated_quantity=requested_quantity,
            unit=sku.package_definition.unit_of_measure,
            purpose=purpose,
            status=InventoryReservation.Status.ALLOCATED,
            actor=actor,
            idempotency_key=idempotency_key,
            expiry_time=expiry_time,
        )
        
        for batch, qty in allocations:
            InventoryLedgerService.post_entry(
                tenant=tenant,
                branch=branch,
                location=source_location,
                sku=sku,
                inventory_batch=batch,
                entry_type=InventoryLedgerEntry.EntryType.RESERVATION,
                quantity_delta=qty,
                unit=sku.package_definition.unit_of_measure,
                base_quantity_delta=qty,
                effective_timestamp=reservation.created_at,
                source_document_type="RESERVATION",
                source_document_id=str(reservation.pk),
                idempotency_key=f"{idempotency_key}-{batch.pk}",
                actor=actor,
                reason_code=purpose,
            )
            
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="InventoryReservation",
            aggregate_id=str(reservation.pk),
            event_type="InventoryReserved",
            payload={"sku_id": str(sku.pk), "allocated_quantity": str(requested_quantity)},
        )
            
        return reservation

    @staticmethod
    @transaction.atomic
    def release_reservation(*, reservation, actor):
        if reservation.status not in [InventoryReservation.Status.PENDING, InventoryReservation.Status.ALLOCATED]:
            raise ValidationError("Only pending or allocated reservations can be released.")
            
        reservation.status = InventoryReservation.Status.RELEASED
        reservation.save()
        
        # Find the ledger entries and reverse them via a RESERVATION_RELEASE entry
        ledger_entries = InventoryLedgerEntry.objects.filter(
            tenant=reservation.tenant,
            source_document_type="RESERVATION",
            source_document_id=str(reservation.pk),
            entry_type=InventoryLedgerEntry.EntryType.RESERVATION
        )
        
        for entry in ledger_entries:
            InventoryLedgerService.post_entry(
                tenant=entry.tenant,
                branch=entry.branch,
                location=entry.location,
                sku=entry.sku,
                inventory_batch=entry.inventory_batch,
                entry_type=InventoryLedgerEntry.EntryType.RESERVATION_RELEASE,
                quantity_delta=entry.quantity_delta,
                unit=entry.unit,
                base_quantity_delta=entry.base_quantity_delta,
                effective_timestamp=reservation.updated_at,
                source_document_type="RESERVATION_RELEASE",
                source_document_id=str(reservation.pk),
                idempotency_key=f"release-{entry.idempotency_key}",
                actor=actor,
                reason_code="RESERVATION_CANCELLED",
            )
            
        emit_event(
            tenant_id=str(reservation.tenant.pk),
            aggregate_type="InventoryReservation",
            aggregate_id=str(reservation.pk),
            event_type="InventoryReservationReleased",
            payload={"sku_id": str(reservation.sku.pk)},
        )
        
        return reservation
