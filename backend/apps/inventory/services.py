import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.audit.service import log_audit
from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
    StocktakeCount,
    StocktakeCountRevision,
    StocktakeSession,
    StockTransfer,
    StockTransferLine,
)
from apps.workflows.service import emit_event


class InventoryLedgerService:
    """
    Authoritative service for posting to the append-only inventory ledger.
    No other service should create InventoryLedgerEntry records directly.
    """

    @staticmethod
    @transaction.atomic
    def post_entry(
        *,
        tenant,
        branch,
        location,
        sku,
        entry_type,
        quantity_delta,
        unit,
        base_quantity_delta,
        effective_timestamp,
        source_document_type,
        source_document_id,
        idempotency_key,
        actor=None,
        inventory_batch=None,
        source_line_id=None,
        correlation_id=None,
        reason_code="",
        notes="",
        reversal_reference=None,
    ):
        zero_recall_event = (
            quantity_delta == 0
            and base_quantity_delta == 0
            and entry_type in (
                InventoryLedgerEntry.EntryType.RECALL_HOLD,
                InventoryLedgerEntry.EntryType.RECALL_RELEASE,
            )
        )
        if not zero_recall_event and (quantity_delta == 0 or base_quantity_delta == 0):
            raise ValidationError("Ledger entries must have a non-zero quantity delta.")

        # Idempotency check handled partially by DB unique constraint, but we check here too
        existing = InventoryLedgerEntry.all_objects.filter(tenant=tenant, idempotency_key=idempotency_key).first()
        if existing:
            return existing

        # Check location capabilities
        if inventory_batch:
            if inventory_batch.quality_status == InventoryBatch.QualityStatus.QUARANTINED and not location.quarantine_capability:
                raise ValidationError(f"Location {location.location_code} cannot hold quarantined stock.")
            if inventory_batch.quality_status == InventoryBatch.QualityStatus.DAMAGED and not location.damaged_goods_capability:
                raise ValidationError(f"Location {location.location_code} cannot hold damaged stock.")
            if inventory_batch.quality_status == InventoryBatch.QualityStatus.EXPIRED and not location.expiry_hold_capability:
                raise ValidationError(f"Location {location.location_code} cannot hold expired stock.")
        
        # Verify sufficient available quantity for outbound transfers/issues
        if base_quantity_delta < 0:
            # We must ensure we don't drop on_hand below 0 unless specific negative stock allowed (disallowed in DawaTrace)
            balance = InventoryBalanceService.get_balance(
                tenant=tenant,
                branch=branch,
                location=location,
                sku=sku,
                inventory_batch=inventory_batch,
            )
            # The available balance might be checked elsewhere for reservations, but on_hand must not go negative
            if balance.on_hand + base_quantity_delta < 0:
                raise ValidationError(f"Insufficient on-hand stock for SKU {sku.sku_code} at {location.location_code}.")

        entry = InventoryLedgerEntry.all_objects.create(
            tenant=tenant,
            branch=branch,
            location=location,
            inventory_batch=inventory_batch,
            sku=sku,
            entry_type=entry_type,
            quantity_delta=quantity_delta,
            unit=unit,
            base_quantity_delta=base_quantity_delta,
            effective_timestamp=effective_timestamp,
            source_document_type=source_document_type,
            source_document_id=source_document_id,
            source_line_id=source_line_id,
            correlation_id=correlation_id or uuid.uuid4(),
            idempotency_key=idempotency_key,
            actor=actor,
            reason_code=reason_code,
            notes=notes,
            reversal_reference=reversal_reference,
        )

        # Update the realtime projection
        InventoryBalanceService.apply_ledger_entry(entry)

        return entry


class InventoryBalanceService:
    """
    Manages the InventoryBalance projection table.
    """

    @staticmethod
    def get_balance(*, tenant, branch, location, sku, inventory_batch=None):
        quality_status = inventory_batch.quality_status if inventory_batch else InventoryBatch.QualityStatus.RELEASED
        expiry_status = "NORMAL"
        
        balance, _ = InventoryBalance.all_objects.select_for_update().get_or_create(
            tenant=tenant,
            branch=branch,
            location=location,
            sku=sku,
            inventory_batch=inventory_batch,
            quality_status=quality_status,
            expiry_status=expiry_status,
            defaults={
                "on_hand": 0,
                "reserved": 0,
                "quarantined": 0,
                "damaged": 0,
                "expired": 0,
                "recalled": 0,
                "in_transit": 0,
                "available": 0,
            }
        )
        return balance

    @staticmethod
    def apply_ledger_entry(entry):
        """
        Dynamically applies the effect of a ledger entry onto the balance projection.
        """
        balance = InventoryBalanceService.get_balance(
            tenant=entry.tenant,
            branch=entry.branch,
            location=entry.location,
            sku=entry.sku,
            inventory_batch=entry.inventory_batch,
        )
        
        # Categorize the entry type impact
        if entry.entry_type in (
            InventoryLedgerEntry.EntryType.RECEIPT,
            InventoryLedgerEntry.EntryType.TRANSFER_IN,
            InventoryLedgerEntry.EntryType.RETURN_IN,
            InventoryLedgerEntry.EntryType.ADJUSTMENT_INCREASE,
            InventoryLedgerEntry.EntryType.STOCKTAKE_GAIN,
        ):
            balance.on_hand += entry.base_quantity_delta
        elif entry.entry_type in (
            InventoryLedgerEntry.EntryType.TRANSFER_OUT,
            InventoryLedgerEntry.EntryType.ISSUE,
            InventoryLedgerEntry.EntryType.RETURN_OUT,
            InventoryLedgerEntry.EntryType.ADJUSTMENT_DECREASE,
            InventoryLedgerEntry.EntryType.STOCKTAKE_LOSS,
            InventoryLedgerEntry.EntryType.WRITE_OFF,
            InventoryLedgerEntry.EntryType.DESTRUCTION,
        ):
            balance.on_hand += entry.base_quantity_delta  # delta should be negative
        elif entry.entry_type == InventoryLedgerEntry.EntryType.RESERVATION:
            balance.reserved += entry.base_quantity_delta
        elif entry.entry_type == InventoryLedgerEntry.EntryType.RESERVATION_RELEASE:
            balance.reserved -= entry.base_quantity_delta
            
        # For damage, expiry, quarantine we might have specific entries that move stock to those buckets 
        # But DawaTrace directive says: "Move damaged stock through explicit ledger entries and custody locations. Do not silently reduce stock."
        # This implies damaged stock is moved to a DAMAGED location using a TRANSFER_OUT and TRANSFER_IN.
        # So the `damaged` or `quarantined` measures might just be the `on_hand` balance AT those specific locations!
        # The prompt says: "Adjust where movements are represented as separate custody locations, but document the exact accounting equation."
        
        # We derive available
        if balance.location.quarantine_capability:
            balance.quarantined = balance.on_hand
        elif balance.location.damaged_goods_capability:
            balance.damaged = balance.on_hand
        elif balance.location.expiry_hold_capability or balance.quality_status == InventoryBatch.QualityStatus.EXPIRED:
            balance.expired = balance.on_hand
            
        balance.recalled = (
            balance.on_hand
            if balance.inventory_batch
            and balance.inventory_batch.recall_status != InventoryBatch.RecallStatus.NONE
            else 0
        )
        balance.available = (
            balance.on_hand
            - balance.reserved
            - balance.quarantined
            - balance.damaged
            - balance.expired
            - balance.recalled
        )
        
        # If the location is a holding area, it's not available
        if (
            balance.location.quarantine_capability
            or balance.location.damaged_goods_capability
            or balance.location.expiry_hold_capability
            or balance.quality_status == InventoryBatch.QualityStatus.EXPIRED
            or balance.recalled > 0
        ):
            balance.available = 0
            
        balance.save()

    @staticmethod
    @transaction.atomic
    def rebuild_all_balances(tenant):
        """
        Wipes the projection and rebuilds it purely from the immutable ledger.
        """
        InventoryBalance.all_objects.filter(tenant=tenant).delete()
        
        entries = InventoryLedgerEntry.all_objects.filter(tenant=tenant).order_by("transaction_timestamp")
        for e in entries:
            InventoryBalanceService.apply_ledger_entry(e)


class InventoryReceiptService:
    @staticmethod
    @transaction.atomic
    def post_receipt(*, tenant, received_batch, receiving_location, actor=None):
        if received_batch.quality_status not in ("RELEASED", "PARTIALLY_RELEASED"):
            raise ValidationError("Only RELEASED or PARTIALLY_RELEASED batches can be posted to inventory.")

        qty = received_batch.accepted_quantity or 0
        if qty <= 0:
            raise ValidationError(f"Batch {received_batch.manufacturer_batch_number} has zero accepted quantity.")

        # Location capability checks
        from apps.medicines.provisioning import _is_cold_chain, _is_controlled
        sku = received_batch.sku
        if _is_controlled(sku) and not receiving_location.controlled_drug_capability:
            raise ValidationError(f"Controlled SKU {sku.sku_code} requires a controlled vault location.")
        if _is_cold_chain(sku) and not receiving_location.cold_chain_capability:
            raise ValidationError(f"Cold-chain SKU {sku.sku_code} requires a cold room location.")

        # Ensure we haven't already posted this batch to avoid duplicates
        existing = InventoryBatch.all_objects.filter(tenant=tenant, source_received_batch=received_batch).first()
        idempotency_key = f"receipt-post-{received_batch.pk}"
        existing_ledger = InventoryLedgerEntry.all_objects.filter(tenant=tenant, idempotency_key=idempotency_key).first()

        if existing and existing_ledger:
            return existing

        receipt_line = received_batch.grn_line
        if existing:
            inv_batch = existing
        else:
            inv_batch = InventoryBatch.all_objects.create(
                tenant=tenant,
                sku=receipt_line.sku,
                manufactured_product=receipt_line.sku.manufactured_product,
                source_received_batch=received_batch,
                manufacturer_batch_number=received_batch.manufacturer_batch_number,
                manufacture_date=received_batch.manufacture_date,
                expiry_date=received_batch.expiry_date,
                quality_status=InventoryBatch.QualityStatus.RELEASED,
            )

        unit = receipt_line.sku.package_definition.unit_of_measure

        if not existing_ledger:
            InventoryLedgerService.post_entry(
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
                idempotency_key=idempotency_key,
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


class FEFOAllocationService:
    """
    Implements First-Expire-First-Out allocation logic.
    """
    @staticmethod
    def allocate_stock(
        *,
        tenant,
        branch,
        location=None,
        sku,
        required_quantity,
        exclude_batches=None,
        include_batches=None,
        minimum_expiry_date=None,
    ):
        """
        Returns a list of tuples: (InventoryBatch, allocated_quantity)
        satisfying the required_quantity via FEFO.
        """
        exclude_batches = exclude_batches or []
        
        # Query balances that are available
        balances = InventoryBalance.all_objects.filter(
            tenant=tenant,
            branch=branch,
            sku=sku,
            available__gt=0,
            inventory_batch__quality_status=InventoryBatch.QualityStatus.RELEASED,
            inventory_batch__recall_status=InventoryBatch.RecallStatus.NONE,
            inventory_batch__expiry_date__gte=minimum_expiry_date or timezone.localdate(),
        ).exclude(
            inventory_batch__in=exclude_batches
        )
        if include_batches is not None:
            balances = balances.filter(inventory_batch__in=include_batches)
        
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
    def reserve_stock(
        *,
        tenant,
        branch,
        source_location,
        sku,
        requested_quantity,
        purpose,
        actor,
        idempotency_key,
        expiry_time=None,
        exclude_batches=None,
        include_batches=None,
        minimum_expiry_date=None,
    ):
        if InventoryReservation.all_objects.filter(tenant=tenant, idempotency_key=idempotency_key).exists():
            return InventoryReservation.all_objects.get(tenant=tenant, idempotency_key=idempotency_key)
            
        # First, try to allocate FEFO
        allocations = FEFOAllocationService.allocate_stock(
            tenant=tenant, 
            branch=branch, 
            location=source_location, 
            sku=sku, 
            required_quantity=requested_quantity,
            exclude_batches=exclude_batches,
            include_batches=include_batches,
            minimum_expiry_date=minimum_expiry_date,
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
        ledger_entries = InventoryLedgerEntry.all_objects.filter(
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

    @staticmethod
    @transaction.atomic
    def expire_reservation(*, reservation, actor=None):
        if reservation.status not in [InventoryReservation.Status.PENDING, InventoryReservation.Status.ALLOCATED]:
            raise ValidationError("Only pending or allocated reservations can be expired.")

        reservation.status = InventoryReservation.Status.EXPIRED
        reservation.save()

        ledger_entries = InventoryLedgerEntry.all_objects.filter(
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
                source_document_type="RESERVATION_EXPIRED",
                source_document_id=str(reservation.pk),
                idempotency_key=f"expire-{entry.idempotency_key}",
                actor=actor,
                reason_code="RESERVATION_EXPIRED",
            )

        emit_event(
            tenant_id=str(reservation.tenant.pk),
            aggregate_type="InventoryReservation",
            aggregate_id=str(reservation.pk),
            event_type="InventoryReservationExpired",
            payload={"sku_id": str(reservation.sku.pk)},
        )

        return reservation

    @staticmethod
    @transaction.atomic
    def fulfill_reservation(
        *,
        reservation,
        quantity,
        inventory_batch,
        actor,
        idempotency_key,
    ):
        reservation = InventoryReservation.all_objects.select_for_update().get(
            pk=reservation.pk,
            tenant=reservation.tenant,
        )
        quantity = Decimal(str(quantity))
        if quantity <= 0:
            raise ValidationError("Reservation fulfilment quantity must be positive.")
        if reservation.status in {
            InventoryReservation.Status.RELEASED,
            InventoryReservation.Status.EXPIRED,
            InventoryReservation.Status.CANCELLED,
        }:
            raise ValidationError("Inactive reservations cannot be fulfilled.")

        reservation_entries = InventoryLedgerEntry.all_objects.filter(
            tenant=reservation.tenant,
            source_document_type="RESERVATION",
            source_document_id=str(reservation.pk),
            entry_type=InventoryLedgerEntry.EntryType.RESERVATION,
            inventory_batch=inventory_batch,
        )
        reserved_for_batch = sum(
            (entry.base_quantity_delta for entry in reservation_entries),
            Decimal("0"),
        )
        fulfilment_entries = InventoryLedgerEntry.all_objects.filter(
            tenant=reservation.tenant,
            source_document_type="RESERVATION_FULFILMENT",
            source_document_id=str(reservation.pk),
            entry_type=InventoryLedgerEntry.EntryType.RESERVATION_RELEASE,
            inventory_batch=inventory_batch,
        )
        already_fulfilled_for_batch = sum(
            (entry.base_quantity_delta for entry in fulfilment_entries),
            Decimal("0"),
        )
        if already_fulfilled_for_batch + quantity > reserved_for_batch:
            raise ValidationError("Cannot fulfil more than the reserved batch quantity.")

        InventoryLedgerService.post_entry(
            tenant=reservation.tenant,
            branch=reservation.branch,
            location=reservation.source_location,
            sku=reservation.sku,
            inventory_batch=inventory_batch,
            entry_type=InventoryLedgerEntry.EntryType.RESERVATION_RELEASE,
            quantity_delta=quantity,
            unit=reservation.unit,
            base_quantity_delta=quantity,
            effective_timestamp=timezone.now(),
            source_document_type="RESERVATION_FULFILMENT",
            source_document_id=str(reservation.pk),
            idempotency_key=idempotency_key,
            actor=actor,
            reason_code="SALES_DISPATCH_FULFILMENT",
        )

        total_fulfilled = (
            InventoryLedgerEntry.all_objects.filter(
                tenant=reservation.tenant,
                source_document_type="RESERVATION_FULFILMENT",
                source_document_id=str(reservation.pk),
                entry_type=InventoryLedgerEntry.EntryType.RESERVATION_RELEASE,
            ).aggregate(total=Sum("base_quantity_delta"))["total"]
            or Decimal("0")
        )
        reservation.status = (
            InventoryReservation.Status.FULFILLED
            if total_fulfilled >= reservation.allocated_quantity
            else InventoryReservation.Status.PARTIALLY_FULFILLED
        )
        reservation.save(update_fields=["status", "updated_at"])
        return reservation




class StockTransferService:
    @staticmethod
    def _require_authority(tenant_id, actor, capability="inventory.manage"):
        if not actor or not actor.is_active or not any(actor.has_capability(cap, tenant_id=tenant_id) for cap in ("inventory.manage", capability)):
            raise ValidationError("Stock transfers require inventory.manage authority in this tenant.")

    @staticmethod
    @transaction.atomic
    def request_transfer(
        *,
        tenant,
        transfer_number,
        source_branch,
        dest_branch,
        source_location,
        dest_location,
        requested_by,
        lines_data,
        reason="",
        document_reference="",
    ):
        StockTransferService._require_authority(tenant.pk, requested_by, "inventory.transfer.request")
        if source_location.branch != source_branch or dest_location.branch != dest_branch:
            raise ValidationError("Locations must belong to their respective branches.")
        if source_location == dest_location:
            raise ValidationError("Destination must differ from the source location.")
        if (
            source_location.status != InventoryLocation.Status.ACTIVE
            or dest_location.status != InventoryLocation.Status.ACTIVE
        ):
            raise ValidationError("Stock transfers require active inventory locations.")
        if not lines_data:
            raise ValidationError("A stock transfer requires at least one line.")
        if any(item.tenant_id != tenant.pk for item in (source_branch, dest_branch, source_location, dest_location)):
            raise ValidationError("Transfer branches and locations must belong to this tenant.")
        from apps.medicines.provisioning import _is_cold_chain, _is_controlled

        seen_skus = set()
        for item in lines_data:
            if item["sku"].tenant_id != tenant.pk:
                raise ValidationError("Transfer SKUs must belong to this tenant.")
            quantity = Decimal(str(item["quantity"]))
            if not quantity.is_finite() or quantity <= 0:
                raise ValidationError("Transfer quantities must be finite and positive.")
            if item["sku"].pk in seen_skus:
                raise ValidationError("Choose each transfer SKU only once.")
            seen_skus.add(item["sku"].pk)
            item["quantity"] = quantity
            if _is_cold_chain(item["sku"]) and not dest_location.cold_chain_capability:
                raise ValidationError("Cold-chain stock requires a cold-chain destination.")
            if _is_controlled(item["sku"]) and not dest_location.controlled_drug_capability:
                raise ValidationError("Controlled stock requires a controlled-drug destination.")
        if StockTransfer.all_objects.filter(
            tenant=tenant,
            transfer_number=transfer_number,
        ).exists():
            raise ValidationError(
                {"transfer_number": "This transfer number already exists."}
            )

        transfer = StockTransfer.all_objects.create(
            tenant=tenant,
            transfer_number=transfer_number,
            source_branch=source_branch,
            destination_branch=dest_branch,
            source_location=source_location,
            destination_location=dest_location,
            requested_by=requested_by,
            status=StockTransfer.Status.SUBMITTED,
            reason=reason,
            document_reference=document_reference,
        )

        for line in lines_data:
            sku = line["sku"]
            qty = line["quantity"]
            StockTransferLine.all_objects.create(
                tenant=tenant,
                transfer=transfer,
                sku=sku,
                requested_quantity=qty,
                unit=sku.package_definition.unit_of_measure,
            )

        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="StockTransfer",
            aggregate_id=str(transfer.pk),
            event_type="StockTransferCreated",
            payload={"transfer_number": transfer_number},
        )
        return transfer

    @staticmethod
    @transaction.atomic
    def approve_transfer(*, transfer, approver):
        StockTransferService._require_authority(transfer.tenant_id, approver, "inventory.transfer.approve")
        transfer = StockTransfer.all_objects.select_for_update().get(
            tenant=transfer.tenant,
            pk=transfer.pk,
        )
        if transfer.status != StockTransfer.Status.SUBMITTED:
            raise ValidationError("Only submitted transfers can be approved.")
        if transfer.requested_by_id and transfer.requested_by_id == approver.pk:
            raise ValidationError(
                "The requester cannot approve their own stock transfer."
            )
        transfer.status = StockTransfer.Status.APPROVED
        transfer.approved_by = approver
        transfer.save(update_fields=["status", "approved_by", "updated_at"])
        emit_event(
            tenant_id=str(transfer.tenant.pk),
            aggregate_type="StockTransfer",
            aggregate_id=str(transfer.pk),
            event_type="StockTransferApproved",
            payload={},
        )
        return transfer

    @staticmethod
    @transaction.atomic
    def allocate_and_dispatch(*, transfer, dispatcher):
        StockTransferService._require_authority(transfer.tenant_id, dispatcher, "inventory.transfer.dispatch")
        transfer = StockTransfer.all_objects.select_for_update().get(
            tenant=transfer.tenant,
            pk=transfer.pk,
        )
        if transfer.status != StockTransfer.Status.APPROVED:
            raise ValidationError("Only approved transfers can be dispatched.")

        # Allocate FEFO and dispatch
        for line in StockTransferLine.all_objects.select_for_update().filter(
            tenant=transfer.tenant, transfer=transfer
        ):
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
            line.save(
                update_fields=[
                    "allocated_quantity",
                    "dispatched_quantity",
                    "updated_at",
                ]
            )

        transfer.status = StockTransfer.Status.DISPATCHED
        transfer.dispatched_by = dispatcher
        transfer.dispatch_timestamp = timezone.now()
        transfer.save(
            update_fields=[
                "status",
                "dispatched_by",
                "dispatch_timestamp",
                "updated_at",
            ]
        )

        emit_event(
            tenant_id=str(transfer.tenant.pk),
            aggregate_type="StockTransfer",
            aggregate_id=str(transfer.pk),
            event_type="StockTransferDispatched",
            payload={},
        )
        return transfer

    @staticmethod
    @transaction.atomic
    def receive_transfer(
        *,
        transfer,
        receiver,
        received_lines_data,
        idempotency_key,
    ):
        StockTransferService._require_authority(transfer.tenant_id, receiver, "inventory.transfer.receive")
        transfer = StockTransfer.all_objects.select_for_update().get(
            tenant=transfer.tenant,
            pk=transfer.pk,
        )
        if not str(idempotency_key or "").strip():
            raise ValidationError("Transfer receiving requires an idempotency key.")
        if not received_lines_data:
            raise ValidationError("Record at least one physical receipt line.")
        receipt_prefix = f"transfer-receive-{idempotency_key}-"
        existing_entries = list(InventoryLedgerEntry.all_objects.filter(
            tenant=transfer.tenant,
            idempotency_key__startswith=receipt_prefix,
        ))
        if existing_entries:
            original = {}
            for entry in existing_entries:
                if entry.source_document_type != "STOCK_TRANSFER" or entry.source_document_id != str(transfer.pk):
                    raise ValidationError("This receiving idempotency key belongs to a different stock transfer.")
                original[(entry.source_line_id, str(entry.inventory_batch_id), entry.reason_code)] = entry.base_quantity_delta
            supplied = {}
            for data in received_lines_data:
                for field, code in (("quantity", "TRANSFER_RECEIPT"), ("damaged", "TRANSFER_DAMAGE_RECEIPT")):
                    quantity = Decimal(str(data.get(field, 0)))
                    if not quantity.is_finite() or quantity < 0:
                        raise ValidationError("Transfer receipt quantities must be finite and non-negative.")
                    if quantity:
                        key = (str(data["line_id"]), str(data["batch_id"]), code)
                        if key in supplied:
                            raise ValidationError("Choose each receipt batch/line only once.")
                        supplied[key] = quantity
            if supplied != original:
                raise ValidationError("This idempotency key was already used for a different physical receipt.")
            return transfer
        if transfer.status not in [
            StockTransfer.Status.DISPATCHED,
            StockTransfer.Status.IN_TRANSIT,
            StockTransfer.Status.PARTIALLY_RECEIVED,
        ]:
            raise ValidationError("Transfer is not in a receivable state.")

        damaged_location = None
        seen_receipt_lines = set()
        for data in received_lines_data:
            receipt_line_key = (str(data["line_id"]), str(data["batch_id"]))
            if receipt_line_key in seen_receipt_lines:
                raise ValidationError("Choose each receipt batch/line only once.")
            seen_receipt_lines.add(receipt_line_key)
            try:
                line = StockTransferLine.all_objects.select_for_update().get(
                    tenant=transfer.tenant,
                    transfer=transfer,
                    pk=data["line_id"],
                )
            except StockTransferLine.DoesNotExist as exc:
                raise ValidationError(
                    "A receipt line is outside the selected transfer."
                ) from exc
            try:
                batch = InventoryBatch.all_objects.get(
                    tenant=transfer.tenant,
                    sku=line.sku,
                    pk=data["batch_id"],
                )
            except InventoryBatch.DoesNotExist as exc:
                raise ValidationError(
                    "A received batch is outside the transfer line SKU."
                ) from exc

            qty = Decimal(str(data["quantity"]))
            damaged = Decimal(str(data.get("damaged", Decimal("0"))))
            if not qty.is_finite() or not damaged.is_finite() or qty < 0 or damaged < 0 or qty + damaged <= 0:
                raise ValidationError("Transfer receipts require finite non-negative quantities with at least one unit received.")
            dispatched_for_batch = -(
                InventoryLedgerEntry.all_objects.filter(
                    tenant=transfer.tenant,
                    source_document_type="STOCK_TRANSFER",
                    source_document_id=str(transfer.pk),
                    source_line_id=str(line.pk),
                    inventory_batch=batch,
                    entry_type=InventoryLedgerEntry.EntryType.TRANSFER_OUT,
                ).aggregate(total=Sum("base_quantity_delta"))["total"]
                or Decimal("0")
            )
            already_received_for_batch = (
                InventoryLedgerEntry.all_objects.filter(
                    tenant=transfer.tenant,
                    source_document_type="STOCK_TRANSFER",
                    source_document_id=str(transfer.pk),
                    source_line_id=str(line.pk),
                    inventory_batch=batch,
                    entry_type=InventoryLedgerEntry.EntryType.TRANSFER_IN,
                ).aggregate(total=Sum("base_quantity_delta"))["total"]
                or Decimal("0")
            )
            if dispatched_for_batch <= 0:
                raise ValidationError(
                    f"Batch {batch.manufacturer_batch_number} was not dispatched for this transfer line."
                )
            remaining_for_batch = dispatched_for_batch - already_received_for_batch
            if qty + damaged > remaining_for_batch:
                raise ValidationError(
                    f"Receipt exceeds the remaining dispatched quantity for batch {batch.manufacturer_batch_number}."
                )
            if (
                (qty + damaged < remaining_for_batch or damaged > 0)
                and not data.get("discrepancy_reason", "").strip()
            ):
                raise ValidationError(
                    "Partial or damaged receipts require a discrepancy reason."
                )

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
                    idempotency_key=f"{receipt_prefix}{line.pk}-{batch.pk}-accepted",
                    actor=receiver,
                    reason_code="TRANSFER_RECEIPT",
                )
                line.received_quantity += qty

            if damaged > 0:
                if damaged_location is None:
                    damaged_location = (
                        InventoryLocation.all_objects.select_related("branch")
                        .filter(
                            tenant=transfer.tenant,
                            branch=transfer.destination_branch,
                            damaged_goods_capability=True,
                            status=InventoryLocation.Status.ACTIVE,
                        )
                        .first()
                    )
                if damaged_location is None:
                    raise ValidationError(
                        "The destination branch has no active damaged-goods custody location."
                    )
                InventoryLedgerService.post_entry(
                    tenant=transfer.tenant,
                    branch=transfer.destination_branch,
                    location=damaged_location,
                    sku=line.sku,
                    inventory_batch=batch,
                    entry_type=InventoryLedgerEntry.EntryType.TRANSFER_IN,
                    quantity_delta=damaged,
                    unit=line.unit,
                    base_quantity_delta=damaged,
                    effective_timestamp=timezone.now(),
                    source_document_type="STOCK_TRANSFER",
                    source_document_id=str(transfer.pk),
                    source_line_id=str(line.pk),
                    idempotency_key=f"{receipt_prefix}{line.pk}-{batch.pk}-damaged",
                    actor=receiver,
                    reason_code="TRANSFER_DAMAGE_RECEIPT",
                    notes=data.get("discrepancy_reason", ""),
                )
                line.damaged_quantity += damaged
            if data.get("discrepancy_reason"):
                line.discrepancy_reason = data["discrepancy_reason"]
            line.save(
                update_fields=[
                    "received_quantity",
                    "damaged_quantity",
                    "discrepancy_reason",
                    "updated_at",
                ]
            )

        remaining = StockTransferLine.all_objects.filter(
            tenant=transfer.tenant,
            transfer=transfer,
        ).filter(
            dispatched_quantity__gt=(
                F("received_quantity") + F("damaged_quantity")
            )
        )
        transfer.status = (
            StockTransfer.Status.PARTIALLY_RECEIVED
            if remaining.exists()
            else StockTransfer.Status.RECEIVED
        )
        transfer.received_by = receiver
        if transfer.status == StockTransfer.Status.RECEIVED:
            transfer.receipt_timestamp = timezone.now()
        transfer.save(
            update_fields=[
                "status",
                "received_by",
                "receipt_timestamp",
                "updated_at",
            ]
        )

        emit_event(
            tenant_id=str(transfer.tenant.pk),
            aggregate_type="StockTransfer",
            aggregate_id=str(transfer.pk),
            event_type=(
                "StockTransferReceived"
                if transfer.status == StockTransfer.Status.RECEIVED
                else "StockTransferPartiallyReceived"
            ),
            payload={},
        )
        return transfer

    @staticmethod
    @transaction.atomic
    def reject_transfer(*, transfer, actor, reason=""):
        StockTransferService._require_authority(transfer.tenant_id, actor, "inventory.transfer.approve")
        transfer = StockTransfer.all_objects.select_for_update().get(
            tenant=transfer.tenant, pk=transfer.pk
        )
        if transfer.status != StockTransfer.Status.SUBMITTED:
            raise ValidationError("Only submitted transfers can be rejected.")
        transfer.status = StockTransfer.Status.REJECTED
        transfer.reason = reason or transfer.reason
        transfer.save(update_fields=["status", "reason", "updated_at"])
        emit_event(
            tenant_id=str(transfer.tenant.pk),
            aggregate_type="StockTransfer",
            aggregate_id=str(transfer.pk),
            event_type="StockTransferRejected",
            payload={"reason": reason},
        )
        return transfer

    @staticmethod
    @transaction.atomic
    def cancel_transfer(*, transfer, actor, reason=""):
        StockTransferService._require_authority(transfer.tenant_id, actor)
        transfer = StockTransfer.all_objects.select_for_update().get(
            tenant=transfer.tenant, pk=transfer.pk
        )
        if transfer.status not in (
            StockTransfer.Status.DRAFT,
            StockTransfer.Status.SUBMITTED,
            StockTransfer.Status.APPROVED,
        ):
            raise ValidationError("Dispatched or received transfers cannot be cancelled.")
        transfer.status = StockTransfer.Status.CANCELLED
        transfer.reason = reason or transfer.reason
        transfer.save(update_fields=["status", "reason", "updated_at"])
        emit_event(
            tenant_id=str(transfer.tenant.pk),
            aggregate_type="StockTransfer",
            aggregate_id=str(transfer.pk),
            event_type="StockTransferCancelled",
            payload={"reason": reason},
        )
        return transfer


class InventoryAdjustmentService:
    @staticmethod
    @transaction.atomic
    def request_adjustment(*, tenant, branch, location, sku, batch, delta, reason, actor, idempotency_key):
        StockTransferService._require_authority(tenant.pk, actor)
        delta = Decimal(str(delta))
        if not delta.is_finite() or delta == 0 or not str(reason or "").strip():
            raise ValidationError("A non-zero finite adjustment and investigation reason are required.")
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

class InventoryWriteOffService:
    @staticmethod
    @transaction.atomic
    def write_off_stock(*, tenant, branch, location, sku, batch, quantity, reason, actor, idempotency_key):
        StockTransferService._require_authority(tenant.pk, actor)
        quantity = Decimal(str(quantity))
        if not quantity.is_finite() or not str(reason or "").strip():
            raise ValidationError("A finite write-off quantity and reason are required.")
        if quantity <= 0:
            raise ValidationError("Write-off quantity must be positive.")
            
        entry = InventoryLedgerService.post_entry(
            tenant=tenant,
            branch=branch,
            location=location,
            sku=sku,
            inventory_batch=batch,
            entry_type=InventoryLedgerEntry.EntryType.WRITE_OFF,
            quantity_delta=-quantity,
            unit=sku.package_definition.unit_of_measure,
            base_quantity_delta=-quantity,
            effective_timestamp=timezone.now(),
            source_document_type="WRITE_OFF",
            source_document_id=idempotency_key,
            idempotency_key=idempotency_key,
            actor=actor,
            reason_code=reason,
        )
        
        emit_event(tenant_id=str(tenant.pk), aggregate_type="InventoryWriteOff", aggregate_id=str(entry.pk), event_type="InventoryWriteOffPosted", payload={"quantity": str(quantity)})
        return entry

class StocktakeService:
    @staticmethod
    def _require_authority(tenant_id, actor):
        if not actor or not actor.is_active or not actor.has_capability("inventory.manage", tenant_id=tenant_id):
            raise ValidationError("Stocktake changes require inventory.manage authority in this tenant.")

    @staticmethod
    def _line_key(location_id, sku_id, batch_id):
        return f"{location_id}:{sku_id}:{batch_id or ''}"

    @staticmethod
    def completeness(session):
        counts = list(StocktakeCount.all_objects.filter(tenant_id=session.tenant_id, session=session, voided=False))
        expected = session.scope_snapshot
        keys = {
            StocktakeService._line_key(count.location_id, count.sku_id, count.batch_id)
            for count in counts if count.counted_quantity is not None
        }
        required = list(expected or [])
        if session.scope == "FULL" and expected is not None:
            # A new batch arriving after opening must not hide behind an empty
            # location confirmation or be omitted from a FULL count.
            existing_keys = {line["key"] for line in required}
            current = InventoryBalance.all_objects.filter(tenant_id=session.tenant_id, location__stocktake_sessions=session, on_hand__gt=0).select_related("location", "sku", "inventory_batch")
            for balance in current:
                key = StocktakeService._line_key(balance.location_id, balance.sku_id, balance.inventory_batch_id)
                if key not in existing_keys:
                    required.append({"key": key, "location_id": str(balance.location_id), "location_name": balance.location.name,
                                     "sku_id": str(balance.sku_id), "sku_code": balance.sku.sku_code, "sku_name": balance.sku.display_name,
                                     "batch_id": str(balance.inventory_batch_id) if balance.inventory_batch_id else None,
                                     "batch_number": balance.inventory_batch.manufacturer_batch_number if balance.inventory_batch_id else None,
                                     "added_after_opening": True})
                    existing_keys.add(key)
        missing = [line for line in required if line["key"] not in keys]
        populated_locations = {line["location_id"] for line in required}
        counted_locations = {str(count.location_id) for count in counts}
        empty_locations = [
            str(location_id) for location_id in InventoryLocation.all_objects.filter(tenant_id=session.tenant_id, stocktake_sessions=session).values_list("pk", flat=True)
            if str(location_id) not in populated_locations
            and str(location_id) not in counted_locations
            and str(location_id) not in session.empty_location_confirmations
        ]
        snapshot_available = expected is not None
        return {
            "snapshot_available": snapshot_available,
            "required_lines": len(required),
            "counted_lines": len(counts),
            "missing_lines": missing,
            "unconfirmed_empty_location_ids": empty_locations if session.scope == "FULL" else [],
            "complete": bool(snapshot_available and not missing and not empty_locations)
            if session.scope == "FULL" else bool(counts),
        }

    @staticmethod
    @transaction.atomic
    def open_stocktake(*, tenant, branch, locations, scope, creator):
        StocktakeService._require_authority(tenant.pk, creator)
        locations = list(locations)
        if not locations:
            raise ValidationError("A stocktake needs at least one inventory location.")
        if branch.tenant_id != tenant.pk or any(
            location.tenant_id != tenant.pk or location.branch_id != branch.pk
            for location in locations
        ):
            raise ValidationError("The branch and every count location must belong to this tenant and branch.")
        scope = str(scope or "").strip().upper()
        if scope not in {"FULL", "PARTIAL", "CYCLE"}:
            raise ValidationError("Stocktake scope must be FULL, PARTIAL, or CYCLE.")
        session = StocktakeSession.objects.create(
            tenant=tenant,
            branch=branch,
            scope=scope,
            status=StocktakeSession.Status.OPEN,
            created_by=creator,
            start_time=timezone.now(),
        )
        session.locations.set(locations)
        if scope == "FULL":
            balances = InventoryBalance.all_objects.filter(
                tenant=tenant, branch=branch, location__in=locations,
            ).select_related("location", "sku", "inventory_batch").order_by("location_id", "sku_id", "inventory_batch_id")
            snapshot = {}
            for balance in balances:
                key = StocktakeService._line_key(balance.location_id, balance.sku_id, balance.inventory_batch_id)
                snapshot[key] = {
                    "key": key, "location_id": str(balance.location_id), "location_name": balance.location.name,
                    "sku_id": str(balance.sku_id), "sku_code": balance.sku.sku_code, "sku_name": balance.sku.display_name,
                    "batch_id": str(balance.inventory_batch_id) if balance.inventory_batch_id else None,
                    "batch_number": balance.inventory_batch.manufacturer_batch_number if balance.inventory_batch_id else None,
                }
            session.scope_snapshot = list(snapshot.values())
        else:
            session.scope_snapshot = []
        session.save(update_fields=["scope_snapshot", "updated_at"])
        emit_event(tenant_id=str(tenant.pk), aggregate_type="StocktakeSession", aggregate_id=str(session.pk), event_type="StocktakeOpened", payload={})
        log_audit(
            tenant_id=tenant.pk,
            action="INVENTORY_STOCKTAKE_OPENED",
            model_name="StocktakeSession",
            object_id=session.pk,
            actor_id=creator.pk,
            metadata={"branch_id": str(branch.pk), "location_ids": [str(item.pk) for item in locations], "scope": scope},
        )
        return session

    @staticmethod
    @transaction.atomic
    def record_count(*, session, location, sku, batch, counted_quantity, counter, reason=""):
        StocktakeService._require_authority(session.tenant_id, counter)
        session = StocktakeSession.all_objects.select_for_update().get(tenant_id=session.tenant_id, pk=session.pk)
        if session.status != StocktakeSession.Status.OPEN:
            raise ValidationError("Stocktake is not open.")
        if location.tenant_id != session.tenant_id or location.branch_id != session.branch_id:
            raise ValidationError("The count location is outside this stocktake.")
        if not InventoryLocation.all_objects.filter(
            tenant_id=session.tenant_id, pk=location.pk, stocktake_sessions=session
        ).exists():
            raise ValidationError("The count location was not included when this stocktake opened.")
        if sku.tenant_id != session.tenant_id:
            raise ValidationError("The selected SKU belongs to another tenant.")
        if batch is not None and (batch.tenant_id != session.tenant_id or batch.sku_id != sku.pk):
            raise ValidationError("The selected batch does not belong to this tenant and SKU.")
        counted_quantity = Decimal(str(counted_quantity))
        if not counted_quantity.is_finite() or counted_quantity < 0:
            raise ValidationError("A physical count must be finite and non-negative.")
        existing = StocktakeCount.all_objects.select_for_update().filter(
            tenant_id=session.tenant_id,
            session=session,
            location=location,
            sku=sku,
            batch=batch,
            voided=False,
        ).first()
        if existing is not None:
            raise ValidationError("This SKU and batch have already been counted at this location.")
            
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
            first_count=counted_quantity,
            variance=counted_quantity - expected,
            reason=str(reason or "").strip(),
            counter=counter,
            timestamp=timezone.now()
        )
        log_audit(
            tenant_id=session.tenant_id,
            action="INVENTORY_STOCKTAKE_COUNT_RECORDED",
            model_name="StocktakeCount",
            object_id=count.pk,
            actor_id=counter.pk,
            metadata={
                "session_id": str(session.pk),
                "location_id": str(location.pk),
                "sku_id": str(sku.pk),
                "batch_id": str(batch.pk) if batch else None,
                "counted_quantity": str(counted_quantity),
                "variance": str(count.variance),
            },
        )
        return count

    @staticmethod
    @transaction.atomic
    def revise_count(*, session, count_id, actor, reason, expected_updated_at, idempotency_key, counted_quantity=None, void=False):
        StocktakeService._require_authority(session.tenant_id, actor)
        session = StocktakeSession.all_objects.select_for_update().get(tenant_id=session.tenant_id, pk=session.pk)
        reason = str(reason or "").strip()
        if not reason or not str(idempotency_key or "").strip():
            raise ValidationError("A revision reason and idempotency key are required.")
        operation = "VOID" if void else "RECOUNT"
        if not void:
            counted_quantity = Decimal(str(counted_quantity))
            if not counted_quantity.is_finite() or counted_quantity < 0:
                raise ValidationError("A recount must be finite and non-negative.")
        revision = StocktakeCountRevision.all_objects.filter(tenant_id=session.tenant_id, idempotency_key=idempotency_key).first()
        if revision:
            if (str(revision.count_id) != str(count_id) or revision.operation != operation
                    or revision.actor_id != actor.pk or revision.reason != reason
                    or revision.counted_quantity != counted_quantity
                    or revision.requested_updated_at != expected_updated_at):
                raise ValidationError("This idempotency key was already used for a different stocktake revision.")
            return revision.count
        if session.status != StocktakeSession.Status.OPEN:
            raise ValidationError("Only open stocktakes can be corrected.")
        # Lock the count and its mandatory SKU/location, not the nullable batch
        # side of the join. The session anchor above serialises count revisions.
        count = StocktakeCount.all_objects.select_for_update(of=("self", "sku", "location")).filter(tenant_id=session.tenant_id, session=session, pk=count_id).select_related("sku", "location", "batch").first()
        if count is None:
            raise ValidationError("Choose a count from this stocktake.")
        if count.voided:
            raise ValidationError("This count has been voided; record a new count instead.")
        if count.updated_at != expected_updated_at:
            raise ValidationError("This count changed since it was opened. Refresh before recounting.")
        # A recount is a new physical observation; use the balance at the new
        # observation time so movements since the first count are not lost.
        expected = count.expected_quantity if void else InventoryBalanceService.get_balance(
            tenant=session.tenant, branch=session.branch, location=count.location, sku=count.sku, inventory_batch=count.batch,
        ).on_hand
        revision = StocktakeCountRevision.all_objects.create(
            tenant_id=session.tenant_id, count=count, actor=actor, operation=operation,
            idempotency_key=idempotency_key, previous_quantity=count.counted_quantity,
            previous_expected_quantity=count.expected_quantity, counted_quantity=counted_quantity,
            expected_quantity=expected, reason=reason, requested_updated_at=expected_updated_at,
        )
        if void:
            count.voided = True
            count.void_reason = reason
            count.voided_by = actor
            count.voided_at = timezone.now()
        else:
            count.recount = counted_quantity
            count.counted_quantity = counted_quantity
            count.expected_quantity = expected
            count.variance = counted_quantity - expected
            count.reason = reason
            count.timestamp = timezone.now()
        count.save()
        log_audit(tenant_id=session.tenant_id, action=f"INVENTORY_STOCKTAKE_COUNT_{operation}",
                  model_name="StocktakeCount", object_id=count.pk, actor_id=actor.pk,
                  metadata={"session_id": str(session.pk), "revision_id": str(revision.pk), "reason": reason,
                            "previous_quantity": str(revision.previous_quantity), "counted_quantity": str(counted_quantity) if counted_quantity is not None else None})
        return count

    @staticmethod
    @transaction.atomic
    def confirm_empty_location(*, session, location_id, actor, reason):
        StocktakeService._require_authority(session.tenant_id, actor)
        session = StocktakeSession.all_objects.select_for_update().get(tenant_id=session.tenant_id, pk=session.pk)
        location_id = str(location_id)
        reason = str(reason or "").strip()
        if session.status != StocktakeSession.Status.OPEN or session.scope != "FULL":
            raise ValidationError("Empty-location confirmations apply only to open FULL stocktakes.")
        if not reason:
            raise ValidationError("Record how the empty location was physically verified.")
        if not InventoryLocation.all_objects.filter(tenant_id=session.tenant_id, stocktake_sessions=session, pk=location_id).exists():
            raise ValidationError("Choose a location included in this stocktake.")
        if any(line["location_id"] == location_id for line in session.scope_snapshot or []):
            raise ValidationError("This location has snapshot lines. Count every line, including zero physical counts.")
        if InventoryBalance.all_objects.filter(tenant_id=session.tenant_id, location_id=location_id, on_hand__gt=0).exists():
            raise ValidationError("This location now has recorded stock; record its physical counts instead.")
        if location_id in session.empty_location_confirmations:
            return session
        session.empty_location_confirmations[location_id] = {"actor_id": str(actor.pk), "reason": reason, "confirmed_at": timezone.now().isoformat()}
        session.save(update_fields=["empty_location_confirmations", "updated_at"])
        log_audit(tenant_id=session.tenant_id, action="INVENTORY_STOCKTAKE_EMPTY_LOCATION_CONFIRMED",
                  model_name="StocktakeSession", object_id=session.pk, actor_id=actor.pk,
                  metadata={"location_id": location_id, "reason": reason})
        return session

    @staticmethod
    @transaction.atomic
    def cancel(*, session, actor, reason):
        StocktakeService._require_authority(session.tenant_id, actor)
        session = StocktakeSession.all_objects.select_for_update().get(tenant_id=session.tenant_id, pk=session.pk)
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError("A stocktake cancellation reason is required.")
        if session.status == StocktakeSession.Status.CANCELLED:
            return session
        if session.status not in {StocktakeSession.Status.DRAFT, StocktakeSession.Status.SCHEDULED, StocktakeSession.Status.OPEN, StocktakeSession.Status.COUNTING, StocktakeSession.Status.REVIEW}:
            raise ValidationError("Posted or approved stocktakes cannot be cancelled.")
        session.status = StocktakeSession.Status.CANCELLED
        session.cancellation_reason = reason
        session.cancelled_by = actor
        session.end_time = timezone.now()
        session.save(update_fields=["status", "cancellation_reason", "cancelled_by", "end_time", "updated_at"])
        log_audit(tenant_id=session.tenant_id, action="INVENTORY_STOCKTAKE_CANCELLED",
                  model_name="StocktakeSession", object_id=session.pk, actor_id=actor.pk, metadata={"reason": reason})
        emit_event(tenant_id=str(session.tenant_id), aggregate_type="StocktakeSession", aggregate_id=str(session.pk), event_type="StocktakeCancelled", payload={"reason": reason})
        return session

    @staticmethod
    @transaction.atomic
    def post_variances(*, session, approver):
        StocktakeService._require_authority(session.tenant_id, approver)
        session = StocktakeSession.all_objects.select_for_update().get(tenant_id=session.tenant_id, pk=session.pk)
        if session.status == StocktakeSession.Status.POSTED and session.approved_by_id == approver.pk:
            return session
        if session.status != StocktakeSession.Status.OPEN:
            raise ValidationError("Stocktake must be open to post variances.")
        counts = StocktakeCount.all_objects.filter(tenant_id=session.tenant_id, session=session, voided=False)
        if not counts.exists() and not (session.scope == "FULL" and StocktakeService.completeness(session)["complete"]):
            raise ValidationError("Record at least one count before posting stocktake variances.")
        if (StocktakeCount.all_objects.filter(tenant_id=session.tenant_id, session=session, counter=approver).exists()
                or StocktakeCountRevision.all_objects.filter(tenant_id=session.tenant_id, count__session=session, actor=approver).exists()
                or any(item["actor_id"] == str(approver.pk) for item in session.empty_location_confirmations.values())
                or session.created_by_id == approver.pk):
            raise ValidationError("A different authorised operator must approve and post this stocktake.")
        if counts.filter(counted_quantity__isnull=True).exists():
            raise ValidationError("Every stocktake line needs a physical count before posting.")
        if session.scope == "FULL" and not StocktakeService.completeness(session)["complete"]:
            raise ValidationError("Count every opening-scope SKU/batch and verify empty locations before posting a FULL stocktake. Pre-snapshot sessions must be cancelled and reopened.")

        for count in counts:
            count.final_approved_count = count.counted_quantity
            count.save(update_fields=["final_approved_count", "updated_at"])
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
        log_audit(
            tenant_id=session.tenant_id,
            action="INVENTORY_STOCKTAKE_VARIANCES_POSTED",
            model_name="StocktakeSession",
            object_id=session.pk,
            actor_id=approver.pk,
            metadata={"counted_lines": counts.count()},
        )
        return session


class ExpiryControlService:
    @staticmethod
    @transaction.atomic
    def process_expired_batches(tenant, *, as_of=None):
        """
        Find batches that are past their expiry date and move them to EXPIRED quality status.
        Mark quality/availability without fabricating a stock movement. Quantity
        stays in custody until an independently authorised write-off/destruction.
        """
        if not tenant or not getattr(tenant, "pk", None):
            raise ValidationError("Expiry maintenance requires an explicit tenant.")
        as_of = as_of or timezone.localdate()
        expired_batches = InventoryBatch.all_objects.select_for_update().filter(
            tenant=tenant,
            quality_status__in=[InventoryBatch.QualityStatus.RELEASED, InventoryBatch.QualityStatus.QUARANTINED],
            expiry_date__lt=as_of
        )
        processed = 0
        for batch in expired_batches:
            batch.quality_status = InventoryBatch.QualityStatus.EXPIRED
            batch.save(update_fields=["quality_status", "updated_at"])
            # Projection rows can span earlier quality dimensions. Consolidate
            # them under the expired dimension; never delete the source ledger.
            grouped = {}
            for balance in InventoryBalance.all_objects.select_for_update().filter(tenant=tenant, inventory_batch=batch):
                grouped.setdefault((balance.location_id, balance.sku_id, balance.expiry_status), []).append(balance)
            total_on_hand = Decimal("0")
            for balances in grouped.values():
                target = next((item for item in balances if item.quality_status == InventoryBatch.QualityStatus.EXPIRED), balances[0])
                on_hand = sum((item.on_hand for item in balances), Decimal("0"))
                reserved = sum((item.reserved for item in balances), Decimal("0"))
                in_transit = sum((item.in_transit for item in balances), Decimal("0"))
                other_ids = [item.pk for item in balances if item.pk != target.pk]
                if other_ids:
                    InventoryBalance.all_objects.filter(tenant=tenant, pk__in=other_ids).delete()
                target.quality_status = InventoryBatch.QualityStatus.EXPIRED
                target.on_hand = on_hand
                target.reserved = reserved
                target.in_transit = in_transit
                target.expired = on_hand
                target.quarantined = 0
                target.damaged = 0
                target.recalled = on_hand if batch.recall_status != InventoryBatch.RecallStatus.NONE else 0
                target.available = 0
                target.save()
                total_on_hand += on_hand
            log_audit(tenant_id=tenant.pk, action="INVENTORY_BATCH_EXPIRED", model_name="InventoryBatch", object_id=batch.pk,
                      metadata={"as_of": as_of.isoformat(), "expiry_date": batch.expiry_date.isoformat(), "on_hand_preserved": str(total_on_hand), "availability": "0"})
            emit_event(tenant_id=str(tenant.pk), aggregate_type="InventoryBatch", aggregate_id=str(batch.pk), event_type="InventoryBatchExpired",
                       payload={"expiry_date": batch.expiry_date.isoformat(), "as_of": as_of.isoformat()})
            processed += 1
        return processed

class RecallInventoryService:
    @staticmethod
    @transaction.atomic
    def initiate_recall(*, tenant, manufacturer_batch_number, sku=None, actor=None, source_document_id=""):
        query = {"tenant": tenant, "manufacturer_batch_number": manufacturer_batch_number}
        if sku:
            query["sku"] = sku
            
        batches = InventoryBatch.all_objects.select_for_update().filter(**query)
        for batch in batches:
            batch.recall_status = InventoryBatch.RecallStatus.RECALLED
            batch.save(update_fields=["recall_status", "updated_at"])
            
            balances = InventoryBalance.all_objects.filter(
                tenant=tenant,
                inventory_batch=batch,
            ).select_related("branch", "location", "sku", "inventory_batch")
            for balance in balances:
                InventoryLedgerService.post_entry(
                    tenant=tenant,
                    branch=balance.branch,
                    location=balance.location,
                    sku=balance.sku,
                    inventory_batch=batch,
                    entry_type=InventoryLedgerEntry.EntryType.RECALL_HOLD,
                    quantity_delta=0,
                    unit=balance.sku.package_definition.unit_of_measure,
                    base_quantity_delta=0,
                    effective_timestamp=timezone.now(),
                    source_document_type="REGULATORY_ALERT",
                    source_document_id=str(source_document_id or batch.pk),
                    idempotency_key=f"recall-hold:{source_document_id or batch.pk}:{batch.pk}:{balance.pk}",
                    actor=actor,
                    reason_code="REGULATORY_RECALL",
                    notes=f"Regulatory hold for manufacturer batch {manufacturer_batch_number}.",
                )

    @staticmethod
    @transaction.atomic
    def release_recall(*, tenant, manufacturer_batch_number, sku=None, actor=None, source_document_id=""):
        query = {
            "tenant": tenant,
            "manufacturer_batch_number": manufacturer_batch_number,
            "recall_status": InventoryBatch.RecallStatus.RECALLED,
        }
        if sku:
            query["sku"] = sku

        batches = InventoryBatch.all_objects.select_for_update().filter(**query)
        for batch in batches:
            batch.recall_status = InventoryBatch.RecallStatus.NONE
            batch.save(update_fields=["recall_status", "updated_at"])
            balances = InventoryBalance.all_objects.filter(
                tenant=tenant,
                inventory_batch=batch,
            ).select_related("branch", "location", "sku", "inventory_batch")
            for balance in balances:
                InventoryLedgerService.post_entry(
                    tenant=tenant,
                    branch=balance.branch,
                    location=balance.location,
                    sku=balance.sku,
                    inventory_batch=batch,
                    entry_type=InventoryLedgerEntry.EntryType.RECALL_RELEASE,
                    quantity_delta=0,
                    unit=balance.sku.package_definition.unit_of_measure,
                    base_quantity_delta=0,
                    effective_timestamp=timezone.now(),
                    source_document_type="REGULATORY_CLOSURE",
                    source_document_id=str(source_document_id or batch.pk),
                    idempotency_key=f"recall-release:{source_document_id or batch.pk}:{batch.pk}:{balance.pk}",
                    actor=actor,
                    reason_code="REGULATOR_WITHDRAWAL_CONFIRMED",
                    notes=f"Recall hold released for manufacturer batch {manufacturer_batch_number}.",
                )
