"""Independent approval for inventory exceptions and acquisition costs."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.service import log_audit
from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryBatchCost,
    InventoryChangeRequest,
    InventoryLedgerEntry,
    InventoryLocation,
    StockTransfer,
    StockTransferLine,
)
from apps.inventory.services import InventoryLedgerService, StockTransferService
from apps.medicines.models import CommercialSKU


def number(value, *, nonzero=False, integer_digits=11):
    try:
        result = Decimal(str(value))
        normalized = result.normalize() if result else Decimal(0)
        if (
            not result.is_finite()
            or normalized.as_tuple().exponent < -4
            or abs(result) >= Decimal(10) ** integer_digits
            or (nonzero and not result)
        ):
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ValidationError("Enter a finite quantity/cost with at most four decimal places.") from None


def scoped(model, tenant_id, key):
    try:
        obj = model.all_objects.filter(tenant_id=tenant_id, pk=key).first()
    except (ValidationError, ValueError):
        obj = None
    if obj is None:
        raise ValidationError(f"Select a {model.__name__} in this tenant.")
    return obj


def validate_payload(tenant_id, kind, payload):
    if kind == "TRANSFER_LOSS":
        transfer = scoped(StockTransfer, tenant_id, payload.get("transfer_id"))
        if transfer.status not in {"DISPATCHED", "IN_TRANSIT", "PARTIALLY_RECEIVED"}:
            raise ValidationError("Only an outstanding dispatched transfer can have a shortage closed.")
        outstanding = {
            str(line.pk): str(
                line.dispatched_quantity - line.received_quantity - line.damaged_quantity - line.lost_quantity
            )
            for line in StockTransferLine.all_objects.filter(tenant_id=tenant_id, transfer=transfer)
            if line.dispatched_quantity > line.received_quantity + line.damaged_quantity + line.lost_quantity
        }
        if not outstanding:
            raise ValidationError("There is no outstanding transfer shortage.")
        return {"transfer_id": str(transfer.pk), "outstanding": outstanding}
    batch = scoped(InventoryBatch, tenant_id, payload.get("batch_id"))
    sku = scoped(CommercialSKU, tenant_id, payload.get("sku_id") or batch.sku_id)
    if batch.sku_id != sku.pk:
        raise ValidationError("Batch and SKU do not match.")
    if kind == "COST":
        cost = number(payload.get("unit_cost"), integer_digits=14)
        if cost < 0 or not str(payload.get("evidence", "")).strip():
            raise ValidationError(
                "A nonnegative acquisition cost per selling unit and invoice/count evidence are required."
            )
        if InventoryBatchCost.all_objects.filter(tenant_id=tenant_id, batch=batch).exists():
            raise ValidationError("This batch already has an approved acquisition cost.")
        return {
            "batch_id": str(batch.pk),
            "sku_id": str(sku.pk),
            "unit_cost": str(cost),
            "evidence": str(payload["evidence"]).strip()[:2000],
        }
    location = scoped(InventoryLocation, tenant_id, payload.get("location_id"))
    if location.status != "ACTIVE":
        raise ValidationError("Choose an active custody location.")
    delta = number(payload.get("quantity"), nonzero=True)
    if kind in {"WRITE_OFF", "DESTRUCTION"} and delta <= 0:
        raise ValidationError("Enter a positive quantity to remove.")
    if kind == "ADJUSTMENT" and delta > 0 and batch.quality_status != "QUARANTINED":
        raise ValidationError("Investigated adjustment gains must enter quarantine before independent quality release.")
    return {"batch_id": str(batch.pk), "sku_id": str(sku.pk), "location_id": str(location.pk), "quantity": str(delta)}


def retry_matches(existing, *, kind, payload, reason):
    if existing.kind != kind or existing.reason != str(reason).strip():
        return False
    stored = existing.payload
    try:
        if kind == "TRANSFER_LOSS":
            # Outstanding quantities are a request-time snapshot, not part of
            # the caller's identity when the same key is retried.
            return str(payload.get("transfer_id")) == stored.get("transfer_id")
        if str(payload.get("batch_id")) != stored.get("batch_id"):
            return False
        if payload.get("sku_id") is not None and str(payload["sku_id"]) != stored.get("sku_id"):
            return False
        if kind == "COST":
            return (
                number(payload.get("unit_cost"), integer_digits=14) == Decimal(stored.get("unit_cost", "NaN"))
                and str(payload.get("evidence", "")).strip()[:2000] == stored.get("evidence")
            )
        return (
            str(payload.get("location_id")) == stored.get("location_id")
            and number(payload.get("quantity")) == Decimal(stored.get("quantity", "NaN"))
        )
    except (InvalidOperation, TypeError, ValueError, ValidationError):
        return False


@transaction.atomic
def request_change(*, tenant, actor, kind, payload, reason, idempotency_key):
    StockTransferService._require_authority(tenant.pk, actor)
    if (
        kind not in dict(InventoryChangeRequest._meta.get_field("kind").choices)
        or not str(reason).strip()
        or not str(idempotency_key).strip()
    ):
        raise ValidationError("Choose an operation and supply an investigation/evidence reason and retry key.")
    # Serialise the per-tenant retry namespace, including first creation.
    type(tenant).objects.select_for_update().get(pk=tenant.pk)
    existing = InventoryChangeRequest.all_objects.filter(tenant=tenant, idempotency_key=idempotency_key).first()
    if existing:
        # Compare normalized values without rechecking state that the original
        # approval may already have changed (stock, batch cost, transfer status).
        if not retry_matches(existing, kind=kind, payload=payload, reason=reason):
            raise ValidationError("The retry key belongs to a different change request.")
        return existing
    values = validate_payload(tenant.pk, kind, payload)
    request = InventoryChangeRequest.all_objects.create(
        tenant=tenant,
        kind=kind,
        payload=values,
        reason=reason.strip(),
        requested_by=actor,
        idempotency_key=idempotency_key,
    )
    audit(request, actor, "REQUESTED")
    return request


def audit(request, actor, decision):
    log_audit(
        tenant_id=request.tenant_id,
        action=f"INVENTORY_CHANGE_{decision}",
        model_name="InventoryChangeRequest",
        object_id=request.pk,
        actor_id=actor.pk,
        metadata={
            "kind": request.kind,
            "payload": request.payload,
            "reason": request.reason,
            "decision_reason": request.decision_reason,
        },
    )


@transaction.atomic
def decide_change(*, change, actor, approve, reason):
    StockTransferService._require_authority(change.tenant_id, actor)
    change = InventoryChangeRequest.all_objects.select_for_update().get(pk=change.pk, tenant_id=change.tenant_id)
    if actor.pk == change.requested_by_id:
        raise ValidationError("A separate authorized person must decide this request.")
    if not str(reason).strip():
        raise ValidationError("A decision reason is required.")
    target = "POSTED" if approve else "REJECTED"
    if change.status != "PENDING":
        if change.status == target and change.decided_by_id == actor.pk:
            return change
        raise ValidationError("This request already has a final decision.")
    if approve:
        if change.kind == "TRANSFER_LOSS":
            StockTransfer.all_objects.select_for_update().get(tenant_id=change.tenant_id, pk=change.payload["transfer_id"])
        else:
            InventoryBatch.all_objects.select_for_update().get(tenant_id=change.tenant_id, pk=change.payload["batch_id"])
        data = validate_payload(change.tenant_id, change.kind, change.payload)
        if change.kind == "TRANSFER_LOSS":
            transfer = StockTransfer.all_objects.select_for_update().get(
                pk=data["transfer_id"], tenant_id=change.tenant_id
            )
            if str(actor.pk) in {str(transfer.dispatched_by_id), str(transfer.requested_by_id)}:
                raise ValidationError("Transfer shortage approval must be independent of the requester and dispatcher.")
            if data != change.payload:
                raise ValidationError(
                    "Transfer receipts have changed. Reject this request and investigate the current shortage."
                )
            for line in StockTransferLine.all_objects.select_for_update().filter(tenant_id=change.tenant_id, transfer=transfer):
                line.lost_quantity = line.dispatched_quantity - line.received_quantity - line.damaged_quantity
                line.discrepancy_reason = change.reason
                line.save(update_fields=["lost_quantity", "discrepancy_reason", "updated_at"])
            # Source stock already left at dispatch. Never remove it a second time.
            transfer.status = "CLOSED"
            transfer.save(update_fields=["status", "updated_at"])
        elif change.kind == "COST":
            InventoryBatchCost.all_objects.create(
                tenant_id=change.tenant_id,
                batch_id=data["batch_id"],
                unit_cost=data["unit_cost"],
                evidence=data["evidence"],
                approved_request=change,
            )
        else:
            location = scoped(InventoryLocation, change.tenant_id, data["location_id"])
            batch = scoped(InventoryBatch, change.tenant_id, data["batch_id"])
            sku = batch.sku
            quantity = Decimal(data["quantity"])
            delta = quantity if change.kind == "ADJUSTMENT" else -quantity
            balances = list(
                InventoryBalance.all_objects.select_for_update().filter(
                    tenant_id=change.tenant_id, location=location, sku=sku, inventory_batch=batch
                )
            )
            if delta < 0 and -delta > sum((balance.on_hand - balance.reserved for balance in balances), Decimal(0)):
                raise ValidationError("The removal exceeds unreserved stock in this custody location.")
            entry_type = (
                ("ADJUSTMENT_INCREASE" if delta > 0 else "ADJUSTMENT_DECREASE")
                if change.kind == "ADJUSTMENT"
                else change.kind
            )
            change.ledger_entry = InventoryLedgerService.post_entry(
                tenant=change.tenant,
                branch=location.branch,
                location=location,
                sku=sku,
                inventory_batch=batch,
                entry_type=entry_type,
                quantity_delta=delta,
                base_quantity_delta=delta,
                unit=sku.package_definition.unit_of_measure,
                effective_timestamp=timezone.now(),
                source_document_type="APPROVED_INVENTORY_CHANGE",
                source_document_id=str(change.pk),
                idempotency_key=f"inventory-change:{change.pk}",
                actor=actor,
                reason_code=change.kind,
                notes=change.reason + "\nApproval: " + reason.strip(),
            )
    change.status = target
    change.decided_by = actor
    change.decision_reason = reason.strip()
    change.decided_at = timezone.now()
    change.save(update_fields=["status", "decided_by", "decision_reason", "decided_at", "ledger_entry", "updated_at"])
    audit(change, actor, target)
    return change


def valuation(tenant_id):
    """Specific identification at immutable, approved batch acquisition cost."""
    rows = []
    known_value = Decimal(0)
    unknown = 0
    for balance in (
        InventoryBalance.all_objects.filter(tenant_id=tenant_id, on_hand__gt=0)
        .select_related("sku", "location", "inventory_batch", "inventory_batch__acquisition_cost")
        .order_by("sku__sku_code", "location__location_code")
    ):
        cost = getattr(balance.inventory_batch, "acquisition_cost", None)
        value = (balance.on_hand * cost.unit_cost).quantize(Decimal(".0001")) if cost else None
        known_value += value or 0
        unknown += int(cost is None)
        rows.append(
            {
                "balance_id": str(balance.pk),
                "sku_id": str(balance.sku_id),
                "sku_code": balance.sku.sku_code,
                "sku_name": balance.sku.display_name,
                "location_id": str(balance.location_id),
                "location": balance.location.name,
                "batch_id": str(balance.inventory_batch_id) if balance.inventory_batch_id else "",
                "batch_number": balance.inventory_batch.manufacturer_batch_number if balance.inventory_batch else "",
                "quality_status": balance.quality_status,
                "quantity": str(balance.on_hand),
                "unit_cost": str(cost.unit_cost) if cost else None,
                "value": str(value) if value is not None else None,
            }
        )
    custody_value = known_value
    transit_value = Decimal(0)
    transfers = {str(item.pk): item for item in StockTransfer.all_objects.filter(tenant_id=tenant_id, status__in=["DISPATCHED", "IN_TRANSIT", "PARTIALLY_RECEIVED"]).select_related("source_branch", "destination_branch")}
    transit = InventoryLedgerEntry.all_objects.filter(tenant_id=tenant_id, source_document_type="STOCK_TRANSFER", source_document_id__in=transfers, entry_type__in=["TRANSFER_OUT", "TRANSFER_IN"]).values("source_document_id", "source_line_id", "inventory_batch_id").annotate(net=Sum("base_quantity_delta"))
    for movement in transit:
        quantity = -movement["net"]
        if quantity <= 0:
            continue
        batch = InventoryBatch.all_objects.select_related("sku", "acquisition_cost").get(tenant_id=tenant_id, pk=movement["inventory_batch_id"])
        cost = getattr(batch, "acquisition_cost", None)
        value = (quantity * cost.unit_cost).quantize(Decimal(".0001")) if cost else None
        unknown += int(cost is None)
        known_value += value or 0
        transit_value += value or 0
        transfer = transfers[movement["source_document_id"]]
        rows.append({"balance_id": f"transit:{movement['source_document_id']}:{movement['source_line_id']}:{batch.pk}",
            "sku_id": str(batch.sku_id), "sku_code": batch.sku.sku_code, "sku_name": batch.sku.display_name,
            "location_id": "", "location": f"In transit: {transfer.source_branch.name} → {transfer.destination_branch.name}",
            "batch_id": str(batch.pk), "batch_number": batch.manufacturer_batch_number, "quality_status": "IN_TRANSIT",
            "quantity": str(quantity), "unit_cost": str(cost.unit_cost) if cost else None, "value": str(value) if value is not None else None})
    return {
        "method": "SPECIFIC_IDENTIFICATION",
        "currency": "KES",
        "known_value": str(known_value.quantize(Decimal(".0001"))),
        "custody_value": str(custody_value.quantize(Decimal(".0001"))),
        "in_transit_value": str(transit_value.quantize(Decimal(".0001"))),
        "complete": unknown == 0,
        "unvalued_lines": unknown,
        "rows": rows,
        "note": "Physical custody plus outstanding dispatched quantities, each valued once; lost quantities cease to be stock only after independent shortage closure. Unknown acquisition costs are unvalued, never zero or selling price.",
    }
