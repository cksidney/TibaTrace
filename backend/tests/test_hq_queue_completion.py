# ruff: noqa: F811
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from tests.test_pos_retail_transactions import world  # noqa: F401

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, InventoryLocation
from apps.medicines.models import Medicine
from apps.medicines.onboarding_completion import release_opening_setup, stage_opening_setup
from apps.medicines.onboarding_models import LegacyCatalogueImport, LegacyCatalogueItem
from apps.patients.models import Patient
from apps.platform.admin_shell import build_hq_workspace_context
from apps.pricing.models import PriceBookVersion
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


def test_server_queue_paging_searches_beyond_first_page_and_does_not_leak_roles(client):
    tenant = Tenant.objects.create(name="HQ Queue", slug="hq-queue")
    for index in range(55):
        Patient.all_objects.create(tenant=tenant, internal_reference_id=f"QUEUE-{index:03}", first_name=f"Patient {index:03}", last_name="Synthetic")
    owner = get_user_model().objects.create_user(username="queue-owner", tenant=tenant, is_platform_admin=True)
    client.force_login(owner)
    body = client.get("/api/hq/workspace/", {"business_module":"patients", "business_page":2}).json()
    module = next(item for item in body["business_modules"] if item["key"] == "patients")
    assert (module["count"], module["page"], module["pages"], len(module["records"])) == (55, 2, 3, 25)
    body = client.get("/api/hq/workspace/", {"business_module":"patients", "business_q":"QUEUE-000"}).json()
    module = next(item for item in body["business_modules"] if item["key"] == "patients")
    assert module["count"] == 1 and module["records"][0]["reference"] == "QUEUE-000"
    reader = get_user_model().objects.create_user(username="queue-no-role", tenant=tenant)
    protected = build_hq_workspace_context(tenant.pk, actor=reader)
    assert all(not module["records"] and module["count"] == 0 for module in protected["business_modules"])


def opening(world):
    tenant, actor, sku = world["tenant"], world["operator"], world["sku"]
    batch = LegacyCatalogueImport.all_objects.create(tenant=tenant, code="CONFIRMED-SOURCE", source_date=timezone.localdate(), provenance={"fixture":True}, imported_by=actor)
    Medicine.all_objects.create(is_global=True, code="SOURCE-PACK", generic_name="Synthetic reference", source="test", source_version="fixture-1")
    item = LegacyCatalogueItem.all_objects.create(tenant=tenant, import_batch=batch, source_key="synthetic-1", source_row=1, proposed_sku_code="POS-001", source_name="Synthetic reviewed medicine", source_cost=1, source_price=2, source_quantity=999,
        reviewed_by=actor, review={"item_kind":"MEDICINE", "sales_unit":"pack", "pack_description":"Actual reviewed pack", "tax_category":"STANDARD", "master_catalogue_code":"SOURCE-PACK", "confirmed_price":"125", "confirmed_cost":"20", "counted_quantity":"3", "counted_on":timezone.localdate().isoformat(), "batches":[{"batch_number":"OPENING-REAL-001", "expiry_date":(timezone.localdate()+timedelta(days=365)).isoformat(), "quantity":"3"}]})
    quarantine = InventoryLocation.all_objects.create(tenant=tenant, branch=world["branch"], location_code="OPENING-QUAR", name="Opening quarantine", location_type="QUARANTINE", quarantine_capability=True)
    values = {"sku_id":str(sku.pk), "branch_id":str(world["branch"].pk), "quarantine_location_id":str(quarantine.pk), "product_match_confirmed":True, "unit_match_confirmed":True, "storage_requirement":"AMBIENT", "tax_inclusive":True, "reason":"Synthetic actual pack comparison"}
    return item, quarantine, values


def test_reviewed_source_stages_actual_count_not_source_balance_and_retry_is_safe(world):
    item, quarantine, values = opening(world)
    expected = item.updated_at.isoformat()
    staged = stage_opening_setup(item=item, actor=world["operator"], expected_updated_at=expected, values=values)
    assert staged.completion["phase"] == "QUARANTINED"
    balance = InventoryBalance.all_objects.get(location=quarantine)
    assert balance.on_hand == 3 and balance.available == 0
    assert PriceBookVersion.all_objects.get(pk=staged.completion["price_version_id"]).status == "DRAFT"
    retry = stage_opening_setup(item=item, actor=world["operator"], expected_updated_at=expected, values=values)
    assert retry.pk == staged.pk
    assert InventoryLedgerEntry.all_objects.filter(source_document_type="LEGACY_OPENING_SETUP").count() == 1


def test_stage_requires_confirmed_units_complete_batches_permissions_and_tenant(world):
    item, quarantine, values = opening(world)
    values["unit_match_confirmed"] = False
    with pytest.raises(ValidationError):
        stage_opening_setup(item=item, actor=world["operator"], expected_updated_at=item.updated_at.isoformat(), values=values)
    values["unit_match_confirmed"] = True
    reader = get_user_model().objects.create_user(username="opening-reader", tenant=world["tenant"])
    with pytest.raises(PermissionDenied):
        stage_opening_setup(item=item, actor=reader, expected_updated_at=item.updated_at.isoformat(), values=values)
    item.review["batches"] = []
    item.save()
    with pytest.raises(ValidationError, match="Actual batches"):
        stage_opening_setup(item=item, actor=world["operator"], expected_updated_at=item.updated_at.isoformat(), values=values)
    assert not InventoryBalance.all_objects.filter(location=quarantine).exists()


def test_release_requires_independent_authority_and_published_price_then_moves_stock_once(world):
    item, quarantine, values = opening(world)
    staged = stage_opening_setup(item=item, actor=world["operator"], expected_updated_at=item.updated_at.isoformat(), values=values)
    args = dict(item=staged, expected_updated_at=staged.updated_at.isoformat(), destination_location_id=world["store"].pk, reason="Actual independent quality check")
    with pytest.raises(ValidationError, match="independent"):
        release_opening_setup(actor=world["operator"], **args)
    reviewer = get_user_model().objects.create_user(username="opening-quality-reviewer", tenant=world["tenant"], is_superuser=True)
    with pytest.raises(ValidationError, match="published"):
        release_opening_setup(actor=reviewer, **args)
    version = PriceBookVersion.all_objects.get(pk=staged.completion["price_version_id"])
    version.status = "ACTIVE"
    version.approved_by = reviewer
    version.save()
    released = release_opening_setup(actor=reviewer, **args)
    assert released.completion["phase"] == "RELEASED"
    assert InventoryBalance.all_objects.get(location=quarantine).on_hand == 0
    assert InventoryBalance.all_objects.get(location=world["store"], inventory_batch_id=released.completion["batches"][0]["batch_id"]).available == Decimal("3")
    release_opening_setup(actor=reviewer, **args)
    assert InventoryLedgerEntry.all_objects.filter(source_document_type="LEGACY_OPENING_RELEASE").count() == 2
