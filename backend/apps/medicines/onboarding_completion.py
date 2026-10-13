"""Explicit, linked source-to-stock workflow; no guesses or auto activation.

The Manager links an already governed SKU and confirmed selling unit. Opening
quantities enter quarantine only. Price publication and an independent quality
release are separate controls. All writes share one transaction and source row
lock; retries return the original facts rather than doubling opening stock.
"""
import hashlib
import json
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.service import log_audit
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry, InventoryLocation
from apps.inventory.services import InventoryLedgerService
from apps.medicines.models import CommercialSKU
from apps.medicines.onboarding import StaleSetupReview, missing_details
from apps.medicines.onboarding_models import LegacyCatalogueItem
from apps.medicines.services import BranchAssortmentService
from apps.pricing.models import PriceBookEntry, PriceBookVersion
from apps.pricing.versioning import PriceBookVersionService


def _require(actor, tenant_id, *capabilities):
    if actor is None or not actor.is_active or any(not actor.has_capability(cap, tenant_id=tenant_id) for cap in capabilities):
        raise PermissionDenied("Required authority: " + ", ".join(capabilities))


def _lock(item, expected):
    locked = LegacyCatalogueItem.all_objects.select_for_update().select_related("tenant", "reviewed_by").get(pk=item.pk, tenant_id=item.tenant_id)
    if parse_datetime(expected or "") != locked.updated_at:
        raise StaleSetupReview("Setup changed. Reload before continuing.")
    return locked


def _sku(tenant_id, sku_id):
    sku = CommercialSKU.all_objects.select_related("package_definition", "manufactured_product__clinical_product").filter(tenant_id=tenant_id, pk=sku_id).first()
    if sku is None or sku.status != "ACTIVE" or not sku.is_saleable or not sku.package_definition.is_active or sku.manufactured_product.clinical_product.status != "ACTIVE":
        raise ValidationError("Select an active, governed tenant SKU. Create and activate its reviewed product/pack in the catalogue first.")
    return sku


def _storage(tenant_id, branch_id, location_id, *, quarantine):
    location = InventoryLocation.all_objects.filter(tenant_id=tenant_id, branch_id=branch_id, pk=location_id, status="ACTIVE", branch__status="ACTIVE").first()
    if location is None or location.quarantine_capability != quarantine or location.damaged_goods_capability or location.expiry_hold_capability or location.returns_capability:
        raise ValidationError("Select an active " + ("quarantine" if quarantine else "saleable") + " storage location in the selected branch.")
    return location


def _check_storage(sku, location, storage_requirement):
    if storage_requirement == "COLD_CHAIN" and not location.cold_chain_capability:
        raise ValidationError("This SKU requires cold-chain capable storage.")
    if sku.manufactured_product.clinical_product.controlled_classification not in ("", "NONE") and not location.controlled_drug_capability:
        raise ValidationError("This controlled medicine requires controlled-drug storage.")


@transaction.atomic
def stage_opening_setup(*, item, actor, expected_updated_at, values):
    _require(actor, item.tenant_id, "inventory.manage", "catalogue.manage", "pricing.price_book.manage")
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
    locked = LegacyCatalogueItem.all_objects.select_for_update().get(pk=item.pk, tenant_id=item.tenant_id)
    if locked.completion:
        if locked.completion.get("request_hash") == fingerprint:
            return locked
        raise ValidationError("This source row has already been staged with different details.")
    locked = _lock(locked, expected_updated_at)
    blockers = missing_details(locked)
    if blockers:
        raise ValidationError("Manager details are incomplete: " + "; ".join(blockers))
    review = locked.review
    if review.get("item_kind") != "MEDICINE":
        raise ValidationError("This governed medicine workflow requires an actual medicine. Supplies/services need their appropriate product model; do not relabel them as medicines.")
    if not values.get("product_match_confirmed") or not values.get("unit_match_confirmed"):
        raise ValidationError("Explicit product and one-to-one sales-unit confirmation is required.")
    sku = _sku(locked.tenant_id, values["sku_id"])
    if review["sales_unit"].strip().casefold() != sku.package_definition.unit_of_measure.strip().casefold():
        raise ValidationError("Confirmed sales unit does not match the SKU unit. Govern the correct package; do not invent a conversion.")
    if review["tax_category"] != sku.tax_category:
        raise ValidationError("Confirmed tax treatment differs from the SKU. Resolve catalogue governance first.")
    location = _storage(locked.tenant_id, values["branch_id"], values["quarantine_location_id"], quarantine=True)
    _check_storage(sku, location, values["storage_requirement"])
    quantity = Decimal(review["counted_quantity"])
    batches = []
    for details in review.get("batches", []):
        if InventoryBatch.all_objects.filter(tenant_id=locked.tenant_id, manufactured_product=sku.manufactured_product, manufacturer_batch_number=details["batch_number"]).exists():
            raise ValidationError("A confirmed batch already exists. Reconcile it with stocktake/receiving rather than posting duplicate opening stock.")
        batch = InventoryBatch(tenant_id=locked.tenant_id, sku=sku, manufactured_product=sku.manufactured_product,
            manufacturer_batch_number=details["batch_number"], expiry_date=date.fromisoformat(details["expiry_date"]), quality_status=InventoryBatch.QualityStatus.QUARANTINED)
        batch.full_clean()
        batches.append((batch, Decimal(details["quantity"])))
    assortment = BranchAssortmentService.enable_sku_for_branch(tenant=locked.tenant, location=location.branch, sku=sku, actor=actor)
    price_entry, _ = PriceBookVersionService.save_tenant_retail_draft(tenant_id=locked.tenant_id, sku_code=sku.sku_code,
        unit_price=review["confirmed_price"], tax_inclusive=values["tax_inclusive"], actor=actor)
    lineage = []
    for batch, batch_quantity in batches:
        batch.save()
        entry = InventoryLedgerService.post_entry(tenant=locked.tenant, branch=location.branch, location=location, sku=sku,
            inventory_batch=batch, entry_type=InventoryLedgerEntry.EntryType.RECEIPT, quantity_delta=batch_quantity,
            base_quantity_delta=batch_quantity, unit=review["sales_unit"], effective_timestamp=timezone.now(),
            source_document_type="LEGACY_OPENING_SETUP", source_document_id=str(locked.pk), source_line_id=str(batch.pk),
            idempotency_key=f"legacy-opening:{locked.pk}:{batch.pk}", actor=actor, reason_code="CONFIRMED_OPENING_COUNT", notes=values["reason"])
        lineage.append({"batch_id": str(batch.pk), "quantity": str(batch_quantity), "entry_id": str(entry.pk)})
    locked.completion = {"phase": "QUARANTINED" if quantity else "PRICE_REVIEW", "sku_id": str(sku.pk), "sku_code": sku.sku_code,
        "branch_id": str(location.branch_id), "quarantine_location_id": str(location.pk), "assortment_id": str(assortment.pk),
        "price_version_id": str(price_entry.version_id), "staged_by": str(actor.pk), "staged_at": timezone.now().isoformat(),
        "batches": lineage, "request_hash": fingerprint, "reason": values["reason"], "storage_requirement": values["storage_requirement"]}
    locked.save(update_fields=["completion", "updated_at"])
    log_audit(tenant_id=locked.tenant_id, action="LEGACY_OPENING_SETUP_STAGED", model_name="LegacyCatalogueItem", object_id=locked.pk,
        actor_id=actor.pk, metadata=locked.completion)
    return locked


@transaction.atomic
def release_opening_setup(*, item, actor, expected_updated_at, destination_location_id, reason):
    _require(actor, item.tenant_id, "inventory.manage", "quality.release")
    locked = LegacyCatalogueItem.all_objects.select_for_update().get(pk=item.pk, tenant_id=item.tenant_id)
    completion = dict(locked.completion)
    if completion.get("phase") == "RELEASED":
        if completion.get("destination_location_id") != str(destination_location_id):
            raise ValidationError("This opening stock was already released to another location.")
        return locked
    locked = _lock(locked, expected_updated_at)
    if completion.get("phase") != "QUARANTINED":
        raise ValidationError("Only staged quarantined opening stock can be released.")
    if str(actor.pk) in (completion["staged_by"], str(locked.reviewed_by_id)):
        raise ValidationError("An independent quality reviewer must release opening stock, not its Manager/author.")
    version = PriceBookVersion.all_objects.filter(tenant_id=locked.tenant_id, pk=completion["price_version_id"]).first()
    if version is None or not version.applies_on(timezone.localdate()) or version.status not in {"ACTIVE", "SCHEDULED"} or not PriceBookEntry.all_objects.filter(tenant_id=locked.tenant_id, version=version, sku_id=completion["sku_id"]).exists():
        raise ValidationError("The linked price draft must be independently approved, published and effective before opening stock release.")
    sku = _sku(locked.tenant_id, completion["sku_id"])
    source = _storage(locked.tenant_id, completion["branch_id"], completion["quarantine_location_id"], quarantine=True)
    destination = _storage(locked.tenant_id, completion["branch_id"], destination_location_id, quarantine=False)
    _check_storage(sku, destination, completion["storage_requirement"])
    for line in completion["batches"]:
        batch = InventoryBatch.all_objects.select_for_update().get(tenant_id=locked.tenant_id, pk=line["batch_id"], sku=sku)
        if batch.expiry_date <= timezone.localdate() or batch.recall_status != InventoryBatch.RecallStatus.NONE or batch.quality_status != InventoryBatch.QualityStatus.QUARANTINED:
            raise ValidationError("An opening batch is expired, recalled or no longer quarantined; quality release is blocked.")
        quantity = Decimal(line["quantity"])
        common = dict(tenant=locked.tenant, branch=source.branch, sku=sku, inventory_batch=batch, unit=locked.review["sales_unit"],
            effective_timestamp=timezone.now(), source_document_type="LEGACY_OPENING_RELEASE", source_document_id=str(locked.pk),
            source_line_id=str(batch.pk), actor=actor, reason_code="INDEPENDENT_OPENING_RELEASE", notes=reason)
        InventoryLedgerService.post_entry(**common, location=source, entry_type=InventoryLedgerEntry.EntryType.TRANSFER_OUT,
            quantity_delta=-quantity, base_quantity_delta=-quantity, idempotency_key=f"legacy-release-out:{locked.pk}:{batch.pk}")
        batch.quality_status = InventoryBatch.QualityStatus.RELEASED
        batch.save(update_fields=["quality_status", "updated_at"])
        InventoryLedgerService.post_entry(**common, location=destination, entry_type=InventoryLedgerEntry.EntryType.TRANSFER_IN,
            quantity_delta=quantity, base_quantity_delta=quantity, idempotency_key=f"legacy-release-in:{locked.pk}:{batch.pk}")
    locked.completion = {**completion, "phase": "RELEASED", "released_by": str(actor.pk), "released_at": timezone.now().isoformat(),
        "destination_location_id": str(destination.pk), "release_reason": reason}
    locked.save(update_fields=["completion", "updated_at"])
    log_audit(tenant_id=locked.tenant_id, action="LEGACY_OPENING_SETUP_RELEASED", model_name="LegacyCatalogueItem", object_id=locked.pk, actor_id=actor.pk, metadata=locked.completion)
    return locked
