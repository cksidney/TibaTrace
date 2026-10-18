"""Physical quarantine custody before quality release or supplier return."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.models import InventoryBatch, InventoryLedgerEntry
from apps.inventory.services import InventoryBalanceService, InventoryLedgerService, StockTransferService
from apps.medicines.provisioning import _is_cold_chain, _is_controlled
from apps.procurement.models import ReceivedBatch


def validate_location(tenant, batch, location, *, quarantine):
    if (
        batch.tenant_id != tenant.pk
        or location.tenant_id != tenant.pk
        or location.branch_id != batch.grn_line.goods_receipt.receiving_branch_id
        or location.status != "ACTIVE"
    ):
        raise ValidationError("Select active stock custody in the receipt tenant and receiving branch.")
    if quarantine and not location.quarantine_capability:
        raise ValidationError("Choose a quarantine custody location.")
    if not quarantine and (
        location.quarantine_capability
        or location.damaged_goods_capability
        or location.expiry_hold_capability
        or location.returns_capability
    ):
        raise ValidationError("Choose a saleable stock destination.")
    if _is_cold_chain(batch.sku) and not location.cold_chain_capability:
        raise ValidationError("Cold-chain stock requires compatible custody.")
    if _is_controlled(batch.sku) and not location.controlled_drug_capability:
        raise ValidationError("Controlled medicines require controlled custody.")


def resolve_batch(tenant, batch, quality):
    sku = batch.sku
    item = (
        InventoryBatch.all_objects.select_for_update()
        .filter(tenant=tenant, sku=sku, manufacturer_batch_number=batch.manufacturer_batch_number)
        .first()
    )
    if item:
        if item.expiry_date != batch.expiry_date:
            raise ValidationError(
                "Existing physical batch has a different expiry. Reconcile its identity before receipt."
            )
        return item
    return InventoryBatch.all_objects.create(
        tenant=tenant,
        sku=sku,
        manufactured_product=sku.manufactured_product,
        lot_kind="MANUFACTURER" if sku.product_kind == "MEDICINE" else "INTERNAL",
        source_received_batch=batch,
        manufacturer_batch_number=batch.manufacturer_batch_number,
        expiry_date=batch.expiry_date,
        manufacture_date=batch.manufacture_date,
        quality_status=quality,
    )


@transaction.atomic
def stage_quarantine(*, tenant, batch, location, actor, reason):
    StockTransferService._require_authority(tenant.pk, actor)
    if not actor.has_capability("procurement.write", tenant_id=tenant.pk) or not str(reason).strip():
        raise ValidationError("Procurement write authority and physical custody evidence are required.")
    batch = ReceivedBatch.all_objects.select_for_update().get(tenant=tenant, pk=batch.pk)
    validate_location(tenant, batch, location, quarantine=True)
    held_quantity = (batch.received_quantity or 0) - (batch.accepted_quantity or 0)
    if held_quantity <= 0:
        raise ValidationError("There is no unreleased physical quantity to stage in quarantine.")
    existing = InventoryLedgerEntry.all_objects.filter(
        tenant=tenant, idempotency_key=f"quarantine-receipt:{batch.pk}"
    ).first()
    if existing:
        if existing.location_id != location.pk:
            raise ValidationError("This receipt was already staged in another custody location.")
        return existing.inventory_batch
    item = resolve_batch(tenant, batch, "QUARANTINED")
    InventoryLedgerService.post_entry(
        tenant=tenant,
        branch=location.branch,
        location=location,
        sku=batch.sku,
        inventory_batch=item,
        entry_type="RECEIPT",
        quantity_delta=Decimal(held_quantity),
        base_quantity_delta=Decimal(held_quantity),
        unit=batch.sku.package_definition.unit_of_measure,
        effective_timestamp=timezone.now(),
        source_document_type="RECEIVED_BATCH_QUARANTINE",
        source_document_id=str(batch.pk),
        idempotency_key=f"quarantine-receipt:{batch.pk}",
        actor=actor,
        reason_code="PHYSICAL_RECEIVING_CUSTODY",
        notes=reason,
    )
    return item


@transaction.atomic
def release_received_stock(*, tenant, received_batch, receiving_location, actor=None):
    batch = ReceivedBatch.all_objects.select_for_update().get(tenant=tenant, pk=received_batch.pk)
    validate_location(tenant, batch, receiving_location, quarantine=False)
    if batch.quality_status not in {"RELEASED", "PARTIALLY_RELEASED"} or batch.accepted_quantity <= 0:
        raise ValidationError("Only independently accepted quantities can enter saleable stock.")
    already_saleable = (
        InventoryLedgerEntry.all_objects.filter(
            tenant=tenant,
            source_document_id=str(batch.pk),
            source_document_type__in=["RECEIVED_BATCH", "RECEIVED_BATCH_RELEASE"],
            entry_type__in=["RECEIPT", "TRANSFER_IN"],
        ).aggregate(total=Sum("base_quantity_delta"))["total"]
        or 0
    )
    delta = Decimal(batch.accepted_quantity) - Decimal(already_saleable)
    item = resolve_batch(tenant, batch, "RELEASED")
    if delta <= 0:
        return item
    staged = (
        InventoryLedgerEntry.all_objects.filter(tenant=tenant, idempotency_key=f"quarantine-receipt:{batch.pk}")
        .select_related("location__branch")
        .first()
    )
    if item.recall_status != "NONE" or (item.expiry_date and item.expiry_date <= timezone.localdate()):
        raise ValidationError("Recalled or expired stock cannot be quality-released.")
    if item.quality_status not in {"RELEASED", "QUARANTINED"}:
        raise ValidationError("Resolve the physical batch quality hold before release.")
    item.quality_status = "RELEASED"
    item.save(update_fields=["quality_status", "updated_at"])

    common = dict(
        tenant=tenant,
        branch=receiving_location.branch,
        sku=batch.sku,
        inventory_batch=item,
        unit=batch.sku.package_definition.unit_of_measure,
        effective_timestamp=timezone.now(),
        source_document_id=str(batch.pk),
        actor=actor,
        reason_code="PROCUREMENT_QUALITY_RELEASE",
    )
    if staged:
        staged_quantity = (
            InventoryLedgerEntry.all_objects.filter(
                tenant=tenant,
                source_document_id=str(batch.pk),
                source_document_type__in=["RECEIVED_BATCH_QUARANTINE", "RECEIVED_BATCH_RELEASE"],
                location=staged.location,
                inventory_batch=item,
            ).aggregate(total=Sum("base_quantity_delta"))["total"]
            or 0
        )
        source_balance = InventoryBalanceService.get_balance(
            tenant=tenant,
            branch=staged.location.branch,
            location=staged.location,
            sku=batch.sku,
            inventory_batch=item,
        )
        move_quantity = min(delta, Decimal(staged_quantity), source_balance.on_hand - source_balance.reserved)
        if move_quantity < 0:
            move_quantity = Decimal(0)
        if move_quantity:
            InventoryLedgerService.post_entry(
                **common,
                location=staged.location,
                entry_type="TRANSFER_OUT",
                quantity_delta=-move_quantity,
                base_quantity_delta=-move_quantity,
                source_document_type="RECEIVED_BATCH_RELEASE",
                idempotency_key=f"receipt-release-out:{batch.pk}:{batch.accepted_quantity}",
            )
            InventoryLedgerService.post_entry(
                **common,
                location=receiving_location,
                entry_type="TRANSFER_IN",
                quantity_delta=move_quantity,
                base_quantity_delta=move_quantity,
                source_document_type="RECEIVED_BATCH_RELEASE",
                idempotency_key=f"receipt-release-in:{batch.pk}:{batch.accepted_quantity}",
            )
        delta -= move_quantity
    if delta:
        InventoryLedgerService.post_entry(
            **common,
            location=receiving_location,
            entry_type="RECEIPT",
            quantity_delta=delta,
            base_quantity_delta=delta,
            source_document_type="RECEIVED_BATCH",
            idempotency_key=(
                f"receipt-post-{batch.pk}"
                if already_saleable == 0
                else f"receipt-post-{batch.pk}:{batch.accepted_quantity}"
            ),
        )
    return item
