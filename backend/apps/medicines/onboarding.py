"""Audited, tenant-scoped initial setup. Never activates products or posts stock."""
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.medicines.models import Medicine
from apps.medicines.onboarding_models import LegacyCatalogueImport, LegacyCatalogueItem
from apps.workflows.service import emit_event


def assert_setup_access(actor, tenant_id):
    if not actor.is_active or not actor.has_capability("inventory.manage", tenant_id=tenant_id):
        raise PermissionDenied("Inventory management permission is required to complete initial item setup.")


def missing_details(item):
    review = item.review or {}
    if review.get("excluded"):
        return ["Excluded from initial setup"]
    missing = []
    for key, label in (("item_kind", "Item type"), ("sales_unit", "Confirmed sales unit"),
                       ("pack_description", "Pack description"), ("tax_category", "Tax treatment")):
        if not review.get(key):
            missing.append(label)
    if review.get("confirmed_price") is None:
        missing.append("Confirmed selling price")
    quantity = review.get("counted_quantity")
    if quantity is None or not review.get("counted_on"):
        missing.append("Current physical count and count date")
    elif date.fromisoformat(review["counted_on"]) != timezone.localdate():
        missing.append("Reconfirm physical count today")
    if review.get("item_kind") == "MEDICINE":
        if not review.get("master_catalogue_code"):
            missing.append("Reviewed national medicine reference")
        if quantity is not None:
            batches = review.get("batches", [])
            if Decimal(str(quantity)) > 0 and not batches:
                missing.append("Actual batches and expiry dates")
            elif batches and sum((Decimal(str(b["quantity"])) for b in batches), Decimal(0)) != Decimal(str(quantity)):
                missing.append("Batch quantities must equal physical count")
            if any(date.fromisoformat(b["expiry_date"]) <= timezone.localdate() for b in batches):
                missing.append("Expired stock must be separated; it cannot be released")
    if review.get("item_kind") == "SERVICE" and quantity is not None and Decimal(str(quantity)) != 0:
        missing.append("Service items must not be loaded as physical stock")
    return missing


def setup_status(item):
    if (item.review or {}).get("excluded"):
        return "EXCLUDED"
    if not item.review:
        return "AWAITING_MANAGER"
    return "DETAILS_COMPLETE" if not missing_details(item) else "IN_PROGRESS"


class StaleSetupReview(Exception):
    pass


@transaction.atomic
def save_review(*, item, actor, review, expected_updated_at):
    assert_setup_access(actor, item.tenant_id)
    locked = LegacyCatalogueItem.all_objects.select_for_update().get(pk=item.pk, tenant_id=item.tenant_id)
    expected = parse_datetime(expected_updated_at or "")
    if expected is None or expected != locked.updated_at:
        raise StaleSetupReview("This item changed since you opened it. Reload before saving.")
    code = review.get("master_catalogue_code", "")
    if code and not Medicine.all_objects.filter(is_global=True, tenant__isnull=True, code=code).exists():
        raise ValidationError("The national reference code does not exist. Leave it blank until reviewed.")
    today = timezone.localdate()
    if review.get("counted_on") and date.fromisoformat(review["counted_on"]) > today:
        raise ValidationError("A physical count cannot be dated in the future.")
    before = locked.review
    locked.review = review
    locked.reviewed_by = actor
    locked.save(update_fields=["review", "reviewed_by", "updated_at"])
    emit_event(tenant_id=locked.tenant_id, aggregate_type="LEGACY_CATALOGUE_SETUP", aggregate_id=str(locked.pk),
               event_type="LegacyCatalogueDetailsSaved", payload={"actor_id":str(actor.pk), "before":before,
               "after":review, "status":setup_status(locked), "saleable":False})
    return locked


@transaction.atomic
def import_source(*, tenant, actor, payload, apply=False):
    assert_setup_access(actor, tenant.pk)
    if payload.get("tenant_slug") != tenant.slug or payload.get("tenant_name") != tenant.name:
        raise ValidationError("Source tenant identity must match the exact target tenant.")
    rows = payload.get("items", [])
    if not rows or len(rows) != payload.get("expected_rows") or len(rows) > 5000:
        raise ValidationError("Source item count is missing or does not reconcile.")
    keys = [row["source_key"] for row in rows]
    if len(set(keys)) != len(keys):
        raise ValidationError("Duplicate source keys; nothing was imported.")
    prior = LegacyCatalogueImport.all_objects.select_for_update().filter(tenant=tenant, code=payload["import_code"]).first()
    if prior:
        if prior.provenance != payload["provenance"] or LegacyCatalogueItem.all_objects.filter(tenant=tenant, import_batch=prior).count() != len(rows):
            raise ValidationError("Import code already exists with different provenance or incomplete rows.")
        # A retry must not overwrite manager work or change immutable sources.
        return {"dry_run":not apply, "created":0, "existing":len(rows), "count":len(rows)}
    # full_clean performs no writes and makes the dry run validate real columns.
    batch = LegacyCatalogueImport(tenant=tenant, code=payload["import_code"], source_date=payload["source_date"],
                                  provenance=payload["provenance"], imported_by=actor)
    batch.full_clean()
    items = []
    fields = ("source_key", "source_row", "legacy_code", "proposed_sku_code", "source_name", "source_uom",
              "source_cost", "source_price", "source_quantity", "source_product", "source_stock", "source_issues")
    for row in rows:
        obj = LegacyCatalogueItem(tenant=tenant, import_batch=batch, **{k:row[k] for k in fields})
        obj.full_clean(exclude=["import_batch"])
        items.append(obj)
    if apply:
        batch.save()
        LegacyCatalogueItem.all_objects.bulk_create(items)
        emit_event(tenant_id=tenant.pk, aggregate_type="LEGACY_CATALOGUE_SETUP", aggregate_id=str(batch.pk),
                   event_type="LegacyCatalogueSourceImported", payload={"actor_id":str(actor.pk),
                   "import_code":batch.code, "count":len(items), "provenance":batch.provenance, "saleable":False})
    return {"dry_run":not apply, "created":len(items) if apply else 0, "ready_to_stage":len(items), "count":len(items)}
