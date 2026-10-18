import csv
import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.inventory.models import InventoryBalance, InventoryBatch, InventoryLocation, StocktakeCount, StocktakeSession
from apps.inventory.services import StocktakeService
from apps.medicines.models import CommercialSKU

COLUMNS = [
    "session_id",
    "location_id",
    "location_name",
    "sku_id",
    "sku_code",
    "batch_id",
    "batch_number",
    "counted_quantity",
    "reason",
]


def stocktake_template(session):
    if session.status != "OPEN":
        raise ValidationError("Download a count sheet only for an open stocktake.")
    if session.scope == "FULL" and not isinstance(session.scope_snapshot, list):
        raise ValidationError("This full stocktake has no opening snapshot. Reopen it before counting.")
    rows = (
        InventoryBalance.all_objects.filter(
            tenant_id=session.tenant_id, branch_id=session.branch_id, location__stocktake_sessions=session
        )
        .select_related("sku", "inventory_batch", "location")
        .order_by("location_id", "sku_id", "inventory_batch_id")
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    candidates = {}
    if session.scope == "FULL" and isinstance(session.scope_snapshot, list):
        for item in session.scope_snapshot:
            key = (item["location_id"], item["sku_id"], item.get("batch_id") or "")
            candidates[key] = {
                "location_id": item["location_id"],
                "location_name": item["location_name"],
                "sku_id": item["sku_id"],
                "sku_code": item["sku_code"],
                "batch_id": item.get("batch_id") or "",
                "batch_number": item.get("batch_number") or "",
            }
    for balance in rows:
        key = (str(balance.location_id), str(balance.sku_id), str(balance.inventory_batch_id or ""))
        candidates.setdefault(key, {
            "location_id": str(balance.location_id),
            "location_name": balance.location.name,
            "sku_id": str(balance.sku_id),
            "sku_code": balance.sku.sku_code,
            "batch_id": str(balance.inventory_batch_id) if balance.inventory_batch_id else "",
            "batch_number": balance.inventory_batch.manufacturer_batch_number if balance.inventory_batch else "",
        })
    for item in candidates.values():
        values = [
            str(session.pk),
            item["location_id"],
            item["location_name"],
            item["sku_id"],
            item["sku_code"],
            item["batch_id"],
            item["batch_number"],
            "",
            "",
        ]
        writer.writerow(
            ["'" + str(value) if str(value).lstrip().startswith(("=", "+", "-", "@")) else value for value in values]
        )
    return "\ufeff" + output.getvalue()


@transaction.atomic
def upload_counts(*, session, actor, rows, dry_run):
    StocktakeService._require_authority(session.tenant_id, actor)
    session = StocktakeSession.all_objects.select_for_update().get(pk=session.pk, tenant_id=session.tenant_id)
    if session.status != "OPEN" or not isinstance(rows, list) or not 0 < len(rows) <= 5000:
        raise ValidationError("Upload 1–5,000 count rows to an open stocktake.")
    seen = set()
    prepared = []
    for index, row in enumerate(rows, 2):
        try:
            location = InventoryLocation.all_objects.get(
                tenant_id=session.tenant_id,
                pk=row.get("location_id"),
                branch_id=session.branch_id,
                stocktake_sessions=session,
            )
            sku = CommercialSKU.all_objects.get(tenant_id=session.tenant_id, pk=row.get("sku_id"))
            batch = (
                InventoryBatch.all_objects.get(tenant_id=session.tenant_id, pk=row["batch_id"], sku=sku)
                if row.get("batch_id")
                else None
            )
            quantity = Decimal(str(row.get("counted_quantity", "")))
            normalized_quantity = quantity.normalize() if quantity else Decimal(0)
            if (
                str(session.pk) != row.get("session_id")
                or not quantity.is_finite()
                or quantity < 0
                or normalized_quantity.as_tuple().exponent < -4
                or quantity >= Decimal("100000000000")
            ):
                raise ValueError
            if sku.batch_tracking_required and batch is None:
                raise ValueError
        except (
            ValueError,
            ArithmeticError,
            ValidationError,
            InventoryLocation.DoesNotExist,
            CommercialSKU.DoesNotExist,
            InventoryBatch.DoesNotExist,
        ):
            raise ValidationError(
                f"Row {index}: check session, scoped location/SKU/batch and nonnegative physical count."
            ) from None
        key = (location.pk, sku.pk, batch.pk if batch else None)
        if key in seen:
            raise ValidationError(
                f"Row {index}: duplicate count identity. Combine quantities or use the recount workflow."
            )
        seen.add(key)
        reason = str(row.get("reason", "")).strip()[:1000]
        existing = StocktakeCount.all_objects.filter(
            tenant_id=session.tenant_id, session=session, location=location, sku=sku, batch=batch, voided=False
        ).first()
        if existing and (
            existing.counted_quantity != quantity or existing.reason != reason or existing.counter_id != actor.pk
        ):
            raise ValidationError(
                f"Row {index}: this line has already been counted. Use the audited recount workflow to change it."
            )
        if not existing:
            prepared.append((location, sku, batch, quantity, reason))
    if not dry_run:
        for location, sku, batch, quantity, reason in prepared:
            StocktakeService.record_count(
                session=session,
                location=location,
                sku=sku,
                batch=batch,
                counted_quantity=quantity,
                counter=actor,
                reason=reason,
            )
    return {
        "dry_run": dry_run,
        "rows": len(rows),
        "new_counts": len(prepared),
        "existing_counts": len(rows) - len(prepared),
    }
