"""Tenant item-list intake into immutable setup evidence, with blind count sheets.

Uploading source data never creates governed products, prices, batches or stock.
Historical balances are retained only as source evidence, including missing/zero
provenance. Manager review and the existing governed opening workflow stay explicit.
"""
import csv
import hashlib
import io
import json
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.medicines.models import Medicine
from apps.medicines.onboarding import assert_setup_access
from apps.medicines.onboarding_models import LegacyCatalogueImport, LegacyCatalogueItem
from apps.tenancy.models import Tenant
from apps.workflows.service import emit_event

MAX_UPLOAD_ROWS = 5000
TEXT_FIELDS = {
    "item_code": 120, "item_name": 255, "sales_unit": 80, "item_kind": 20,
    "pack_description": 255, "tax_category": 20, "barcode": 100, "master_catalogue_code": 120,
}
NUMERIC_FIELDS = ("cost_price", "selling_price", "source_quantity")
STOCKTAKE_COLUMNS = (
    "item_id", "expected_updated_at", "item_code", "item_name", "sales_unit", "item_kind",
    "batch_number", "expiry_date", "counted_quantity", "counted_on", "notes",
)


def _error(row, field, value, message):
    return {"row": row, "field": field, "value": value, "message": message}


def _decimal(value, *, allow_negative):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Use a decimal number, or leave the cell blank.")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError("Use a decimal number, or leave the cell blank.") from exc
    if not number.is_finite():
        raise ValueError("A finite decimal number is required.")
    if not allow_negative and number < 0:
        raise ValueError("Prices cannot be negative.")
    if abs(number) >= Decimal("100000000000000"):
        raise ValueError("Use at most 14 digits before the decimal point.")
    if number != number.quantize(Decimal("0.0001")):
        raise ValueError("Use at most four decimal places.")
    return format(number.normalize(), "f") if number else "0"


def validate_rows(rows):
    errors, parsed, seen = [], [], {}
    for index, raw in enumerate(rows, start=2):
        if not isinstance(raw, dict):
            errors.append(_error(index, "row", None, "Each row must contain named columns."))
            continue
        source_row = raw.get("_source_row", index)
        if isinstance(source_row, bool) or not isinstance(source_row, int) or not 1 <= source_row <= 2147483647:
            errors.append(_error(index, "_source_row", source_row, "Source row must be a positive whole number."))
            source_row = index
        row_errors = len(errors)
        for field in raw.keys() - (TEXT_FIELDS.keys() | set(NUMERIC_FIELDS) | {"_source_row"}):
            errors.append(_error(source_row, field, raw[field], "This column is not supported by the item upload template."))
        values = {}
        for field, limit in TEXT_FIELDS.items():
            value = raw.get(field, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                errors.append(_error(source_row, field, value, "Use text for this column; preserve codes and leading zeros."))
                value = ""
            value = value.strip()
            values[field] = value
            if len(value) > limit:
                errors.append(_error(source_row, field, value, f"Use at most {limit} characters."))
            if "\x00" in value:
                errors.append(_error(source_row, field, value, "Remove null characters from this value."))
            if field in ("item_code", "item_name", "sales_unit") and not value:
                errors.append(_error(source_row, field, value, "This value is required."))
        for field, choices in (("item_kind", ("MEDICINE", "SUPPLY", "SERVICE")),
                               ("tax_category", ("STANDARD", "ZERO_RATED", "EXEMPT"))):
            if values[field] and values[field] not in choices:
                errors.append(_error(source_row, field, values[field], "Use one of: " + ", ".join(choices)))
        for field in NUMERIC_FIELDS:
            try:
                values[field] = _decimal(raw.get(field), allow_negative=field == "source_quantity")
            except (ValueError, InvalidOperation) as exc:
                errors.append(_error(source_row, field, raw.get(field), str(exc)))
        key = values["item_code"].casefold()
        if key in seen:
            errors.append(_error(source_row, "item_code", values["item_code"],
                                 f"Item code is repeated in this file (first seen on row {seen[key]})."))
        elif key:
            seen[key] = source_row
        if len(errors) == row_errors:
            parsed.append({"values": values, "raw": raw, "source_row": source_row})
    references = {row["values"]["master_catalogue_code"] for row in parsed if row["values"]["master_catalogue_code"]}
    known = set(Medicine.all_objects.filter(is_global=True, tenant__isnull=True, code__in=references).values_list("code", flat=True))
    for row in parsed:
        code = row["values"]["master_catalogue_code"]
        if code and code not in known:
            errors.append(_error(row["source_row"], "master_catalogue_code", code,
                                 "This exact national catalogue code does not exist. Leave it blank until reviewed."))
    return parsed, errors


def _fingerprint(rows, source_date):
    canonical = {"source_date": source_date.isoformat(),
                 "rows": sorted((row["values"] for row in rows), key=lambda value: value["item_code"].casefold())}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _source_item(tenant, batch, row):
    values = row["values"]
    issues = ["Uploaded values are source candidates; Manager confirmation and a current physical count are required."]
    for field, label in (("cost_price", "Source cost"), ("selling_price", "Source selling price"), ("source_quantity", "Source quantity")):
        if values[field] is None:
            issues.append(f"{label} was not supplied; the stored zero is a missing-value sentinel, not a confirmed value.")
    if not values["item_kind"]:
        issues.append("Item type was not supplied; Manager classification is required.")
    if values["source_quantity"] is not None:
        issues.append("Source balance is historical evidence, not a physical stock count.")
    return LegacyCatalogueItem(
        tenant=tenant, import_batch=batch, source_key=values["item_code"], source_row=row["source_row"],
        legacy_code=values["item_code"], proposed_sku_code=values["item_code"],
        source_name=values["item_name"], source_uom=values["sales_unit"],
        source_cost=values["cost_price"] or "0", source_price=values["selling_price"] or "0",
        source_quantity=values["source_quantity"] or "0",
        source_product={"format": "TENANT_ITEM_CSV_V1", "filename": batch.provenance["source_filename"],
                        "source_row": row["source_row"], "raw": row["raw"], "upload_canonical": values},
        source_stock={"source_quantity": row["raw"].get("source_quantity"),
                      "quantity_supplied": values["source_quantity"] is not None,
                      "source_date": batch.source_date.isoformat(), "source_row": row["source_row"]},
        source_issues=issues,
    )


def _retry_matches(batch, rows, fingerprint):
    existing = list(LegacyCatalogueItem.all_objects.filter(tenant_id=batch.tenant_id, import_batch=batch))
    if batch.provenance.get("canonical_content_sha256") != fingerprint or len(existing) != len(rows):
        return False
    stored = {item.legacy_code.casefold(): item for item in existing}
    for row in rows:
        values = row["values"]
        item = stored.get(values["item_code"].casefold())
        if item is None or item.source_product.get("upload_canonical") != values:
            return False
        if (item.source_key != values["item_code"] or item.proposed_sku_code != values["item_code"]
                or item.source_name != values["item_name"] or item.source_uom != values["sales_unit"]
                or item.source_cost != Decimal(values["cost_price"] or "0")
                or item.source_price != Decimal(values["selling_price"] or "0")
                or item.source_quantity != Decimal(values["source_quantity"] or "0")):
            return False
    return True


def import_item_upload(*, tenant, actor, rows, source_date, source_filename, dry_run=True):
    assert_setup_access(actor, tenant.pk)
    result = {"dry_run": dry_run, "received": len(rows), "valid": False, "valid_rows": 0, "errors": [], "ready_to_stage": 0,
              "created": 0, "existing": 0, "import_id": None, "import_code": None}
    if not rows or len(rows) > MAX_UPLOAD_ROWS:
        result["errors"] = [_error(0, "rows", len(rows), f"Upload between 1 and {MAX_UPLOAD_ROWS} item rows.")]
        return result
    parsed, errors = validate_rows(rows)
    result["valid_rows"] = len(rows) - len({error["row"] for error in errors})
    result["errors"] = errors
    if errors:
        return result
    fingerprint = _fingerprint(parsed, source_date)
    import_code = "CSV-" + fingerprint
    # The tenant lock serialises different uploads as well as exact retries. A
    # per-batch lock alone cannot protect cross-file item-code conflicts.
    with transaction.atomic():
        if not dry_run:
            tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
        prior = LegacyCatalogueImport.all_objects.filter(tenant=tenant, code=import_code).first()
        if prior:
            if not _retry_matches(prior, parsed, fingerprint):
                result["errors"] = [_error(0, "rows", None, "The existing import has conflicting immutable source evidence. Contact support; nothing was changed.")]
                return result
            result.update(valid=True, existing=len(rows), ready_to_stage=len(rows), import_id=str(prior.pk), import_code=prior.code)
            return result
        used_codes = {str(code).casefold() for pair in LegacyCatalogueItem.all_objects.filter(tenant=tenant)
                      .values_list("legacy_code", "proposed_sku_code") for code in pair if code}
        for row in parsed:
            code = row["values"]["item_code"]
            if code.casefold() in used_codes:
                result["errors"].append(_error(row["source_row"], "item_code", code,
                    "This item code already exists in an earlier tenant upload. Review the existing item instead of duplicating it."))
        if result["errors"]:
            result["valid_rows"] = len(rows) - len({error["row"] for error in result["errors"]})
            return result
        batch = LegacyCatalogueImport(tenant=tenant, code=import_code, source_date=source_date, imported_by=actor,
            provenance={"format": "TENANT_ITEM_CSV_V1", "source_filename": source_filename,
                        "source_date": source_date.isoformat(), "canonical_content_sha256": fingerprint,
                        "row_count": len(rows), "source_rows": [row["source_row"] for row in parsed]})
        batch.full_clean()
        items = [_source_item(tenant, batch, row) for row in parsed]
        for item in items:
            # Ownership is supplied by the authorised, locked tenant, rather
            # than the CSV. Avoid a redundant FK lookup for every source row.
            item.clean_fields(exclude=["tenant", "import_batch"])
        result.update(valid=True, ready_to_stage=len(rows), import_code=import_code)
        if not dry_run:
            batch.save(force_insert=True)
            LegacyCatalogueItem.all_objects.bulk_create(items)
            emit_event(tenant_id=tenant.pk, aggregate_type="LEGACY_CATALOGUE_SETUP", aggregate_id=str(batch.pk),
                event_type="LegacyCatalogueSourceImported", payload={"actor_id": str(actor.pk),
                "import_code": batch.code, "count": len(items), "provenance": batch.provenance, "saleable": False})
            result.update(created=len(items), import_id=str(batch.pk))
    return result


def spreadsheet_literal(value):
    """Keep tenant-controlled text literal even when opened directly in Excel."""
    text = str(value or "")
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def opening_stocktake_csv(items):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(STOCKTAKE_COLUMNS)
    for item in items:
        if item.completion or (item.review or {}).get("excluded"):
            continue
        review = item.review or {}
        source = (item.source_product or {}).get("upload_canonical", {})
        writer.writerow([str(item.pk), item.updated_at.isoformat(), spreadsheet_literal(item.legacy_code or item.proposed_sku_code),
            spreadsheet_literal(item.source_name), spreadsheet_literal(review.get("sales_unit") or item.source_uom),
            spreadsheet_literal(review.get("item_kind") or source.get("item_kind", "")), "", "", "", "", ""])
    return "\ufeff" + output.getvalue()
