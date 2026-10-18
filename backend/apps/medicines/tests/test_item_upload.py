"""Tenant source uploads and blind stocktake downloads never activate stock."""
import csv
import io
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import Role, UserRole
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry
from apps.medicines.models import CommercialSKU, Medicine
from apps.medicines.onboarding import import_source
from apps.medicines.onboarding_models import LegacyCatalogueImport, LegacyCatalogueItem
from apps.pricing.models import PriceBookEntry
from apps.tenancy.models import Tenant

UPLOAD_URL = "/api/medicines/initial-setup/import/"
TEMPLATE_URL = "/api/medicines/initial-setup/stocktake-template/"


@pytest.fixture
def upload_data(db):
    tenant = Tenant.objects.create(name="Upload Pharmacy", slug="upload-pharmacy")
    actor = get_user_model().objects.create_user(username="upload-admin", is_platform_admin=True)
    client = APIClient()
    client.force_authenticate(user=actor)
    payload = {"source_filename":"tenant-items.csv", "source_date":"2026-10-09", "rows":[{
        "item_code":"ITEM-001", "item_name":"Source item", "sales_unit":"tablet", "item_kind":"MEDICINE",
        "pack_description":"100 tablets", "cost_price":"", "selling_price":"0", "source_quantity":"0",
        "tax_category":"EXEMPT", "barcode":"0012345", "master_catalogue_code":"", "_source_row":2}]}
    return tenant, actor, client, payload


def post(client, tenant, payload):
    return client.post(UPLOAD_URL, payload, format="json", HTTP_X_TENANT_ID=str(tenant.pk))


def sheet(response):
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


@pytest.mark.django_db
def test_default_preview_is_write_free_and_apply_preserves_blank_zero_provenance(upload_data):
    tenant, actor, client, payload = upload_data
    preview = post(client, tenant, payload)
    assert preview.status_code == 200
    assert preview.data["valid"] is True and preview.data["valid_rows"] == 1
    assert preview.data["dry_run"] is True and preview.data["ready_to_stage"] == 1
    assert preview.data["created"] == 0 and preview.data["import_id"] is None
    assert not LegacyCatalogueImport.all_objects.exists()
    assert not LegacyCatalogueItem.all_objects.exists()
    payload["dry_run"] = False
    applied = post(client, tenant, payload)
    assert applied.status_code == 200 and applied.data["created"] == 1
    item = LegacyCatalogueItem.all_objects.get()
    assert item.source_product["raw"]["cost_price"] == ""
    assert item.source_product["raw"]["selling_price"] == "0"
    assert item.source_product["upload_canonical"]["cost_price"] is None
    assert item.source_product["upload_canonical"]["selling_price"] == "0"
    assert item.source_stock["quantity_supplied"] is True
    assert item.source_quantity == 0 and item.source_cost == 0
    assert any("Source cost was not supplied" in issue for issue in item.source_issues)
    assert item.review == {} and item.completion == {}
    assert not Medicine.all_objects.exists()
    assert not CommercialSKU.all_objects.exists()
    assert not InventoryBatch.all_objects.exists()
    assert not InventoryLedgerEntry.all_objects.exists()
    assert not PriceBookEntry.all_objects.exists()


@pytest.mark.django_db
def test_retry_is_canonical_idempotent_and_preserves_original_sources_and_reviews(upload_data):
    tenant, actor, client, payload = upload_data
    payload["dry_run"] = False
    first = post(client, tenant, payload)
    item = LegacyCatalogueItem.all_objects.get()
    item.review = {"notes":"Manager has begun", "excluded": True}
    item.reviewed_by = actor
    item.save()
    updated_at = item.updated_at
    payload["source_filename"] = "renamed-upload.csv"
    payload["rows"][0]["selling_price"] = "0.0000"
    payload["rows"][0]["_source_row"] = 7
    second = post(client, tenant, payload)
    assert second.status_code == 200 and second.data["existing"] == 1
    assert second.data["created"] == 0 and first.data["import_id"] == second.data["import_id"]
    item.refresh_from_db()
    assert item.review["notes"] == "Manager has begun" and item.updated_at == updated_at
    assert item.source_row == 2 and item.source_product["raw"]["selling_price"] == "0"
    assert item.import_batch.provenance["source_filename"] == "tenant-items.csv"
    assert LegacyCatalogueImport.all_objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [
    ("cost_price", "-1"), ("selling_price", "NaN"), ("cost_price", "Infinity"),
    ("source_quantity", "many"), ("selling_price", "0.00001"), ("cost_price", "100000000000000"),
    ("source_quantity", True), ("item_kind", "DRUG"), ("tax_category", "ZERO"),
    ("item_code", ""), ("item_name", ""), ("sales_unit", ""), ("barcode", "x" * 101),
    ("item_name", "bad\x00name"), ("opening_balance", "7"), ("_source_row", -1),
])
def test_invalid_cells_report_row_field_and_never_partially_write(upload_data, field, value):
    tenant, actor, client, payload = upload_data
    good = deepcopy(payload["rows"][0])
    good["item_code"] = "GOOD"
    good["_source_row"] = 3
    payload["rows"][0][field] = value
    payload["rows"].append(good)
    payload["dry_run"] = False
    response = post(client, tenant, payload)
    assert response.status_code == 200
    assert response.data["valid"] is False
    assert any(error["field"] == field for error in response.data["errors"])
    assert response.data["created"] == 0 and response.data["ready_to_stage"] == 0
    assert not LegacyCatalogueItem.all_objects.exists()
    assert not LegacyCatalogueImport.all_objects.exists()


@pytest.mark.django_db
def test_reports_all_cell_errors_and_validates_exact_national_reference(upload_data):
    tenant, actor, client, payload = upload_data
    Medicine.all_objects.create(is_global=True, code="PH100", generic_name="Reference", status="INACTIVE", source="test", source_version="1")
    payload["rows"][0].update(cost_price="bad", selling_price="-2", tax_category="bad")
    response = post(client, tenant, payload)
    assert {error["field"] for error in response.data["errors"]} == {"cost_price", "selling_price", "tax_category"}
    payload["rows"][0].update(cost_price="1", selling_price="2", tax_category="EXEMPT", master_catalogue_code="ph100")
    assert post(client, tenant, payload).data["errors"][0]["field"] == "master_catalogue_code"
    payload["rows"][0]["master_catalogue_code"] = "PH100"
    payload["dry_run"] = False
    assert post(client, tenant, payload).data["created"] == 1
    item = LegacyCatalogueItem.all_objects.get()
    assert not item.review and item.source_product["upload_canonical"]["master_catalogue_code"] == "PH100"


@pytest.mark.django_db
def test_duplicate_codes_are_case_insensitive_within_and_across_imports(upload_data):
    tenant, actor, client, payload = upload_data
    duplicate = deepcopy(payload["rows"][0])
    duplicate["item_code"] = "item-001"
    duplicate["_source_row"] = 3
    payload["rows"].append(duplicate)
    assert post(client, tenant, payload).data["errors"][0]["field"] == "item_code"
    payload["rows"].pop()
    payload["dry_run"] = False
    assert post(client, tenant, payload).data["created"] == 1
    payload["rows"][0]["item_code"] = "item-001"
    payload["source_date"] = "2026-10-10"
    conflict = post(client, tenant, payload)
    assert conflict.data["errors"][0]["field"] == "item_code"
    assert LegacyCatalogueItem.all_objects.count() == 1
    other = Tenant.objects.create(name="Other pharmacy", slug="other-upload")
    assert post(client, other, payload).data["created"] == 1


@pytest.mark.django_db
def test_codes_from_preexisting_legacy_import_are_protected(upload_data):
    tenant, actor, client, payload = upload_data
    legacy = {"tenant_slug":tenant.slug, "tenant_name":tenant.name, "import_code":"PDF-ORIGINAL",
        "source_date":"2026-10-01", "expected_rows":1, "provenance":{"file":"original.pdf"}, "items":[{
            "source_key":"1", "source_row":1, "legacy_code":"ITEM-001", "proposed_sku_code":"LEGACY-001",
            "source_name":"Original", "source_uom":"pcs", "source_cost":"1", "source_price":"2", "source_quantity":"0",
            "source_product":{"file":"original.pdf"}, "source_stock":{"file":"stock.pdf"}, "source_issues":[]}]}
    import_source(tenant=tenant, actor=actor, payload=legacy, apply=True)
    payload["dry_run"] = False
    assert post(client, tenant, payload).data["errors"][0]["field"] == "item_code"
    assert LegacyCatalogueItem.all_objects.count() == 1


@pytest.mark.django_db
def test_immutable_source_conflict_is_refused_even_if_fingerprint_exists(upload_data):
    tenant, actor, client, payload = upload_data
    payload["dry_run"] = False
    post(client, tenant, payload)
    item = LegacyCatalogueItem.all_objects.get()
    item.source_name = "Tampered"
    item.save()
    response = post(client, tenant, payload)
    assert response.data["errors"][0]["field"] == "rows" and response.data["existing"] == 0
    item.refresh_from_db()
    assert item.source_name == "Tampered"


@pytest.mark.django_db
def test_permissions_scope_and_malformed_schema(upload_data):
    tenant, actor, client, payload = upload_data
    assert client.post(UPLOAD_URL, payload, format="json").status_code == 403
    assert client.get(TEMPLATE_URL).status_code == 403
    reader = get_user_model().objects.create_user(username="upload-reader", tenant=tenant)
    client.force_authenticate(user=reader)
    assert post(client, tenant, payload).status_code == 403
    assert client.get(TEMPLATE_URL, HTTP_X_TENANT_ID=str(tenant.pk)).status_code == 403
    client.force_authenticate(user=actor)
    bad = deepcopy(payload)
    bad["source_date"] = "yesterday"
    assert post(client, tenant, bad).status_code == 400
    bad = deepcopy(payload)
    del bad["source_filename"]
    assert post(client, tenant, bad).status_code == 400
    for rows in ([], [payload["rows"][0]] * 5001):
        bad = {**payload, "rows":rows, "dry_run":False}
        response = post(client, tenant, bad)
        assert response.status_code == 200 and response.data["errors"] and response.data["created"] == 0
    assert not LegacyCatalogueImport.all_objects.exists()


@pytest.mark.django_db
def test_stocktake_is_blind_includes_all_pages_and_zeroes_and_obeys_import_scope(upload_data):
    tenant, actor, client, payload = upload_data
    payload["rows"] = [{**payload["rows"][0], "item_code":f"ITEM-{n:03}", "_source_row":n + 2,
                        "source_quantity":"0" if n % 2 else "500", "cost_price":"1.25", "selling_price":"3.50"} for n in range(35)]
    payload["dry_run"] = False
    first = post(client, tenant, payload)
    items = list(LegacyCatalogueItem.all_objects.order_by("source_row"))
    items[0].review = {"excluded":True}
    items[0].save()
    items[1].completion = {"phase":"PRICE_REVIEW"}
    items[1].save()
    items[2].review = {"sales_unit":"box", "item_kind":"SUPPLY"}
    items[2].save()
    response = client.get(TEMPLATE_URL, {"import_id":first.data["import_id"]}, HTTP_X_TENANT_ID=str(tenant.pk))
    assert response.status_code == 200 and response.content.startswith(b"\xef\xbb\xbf")
    assert response["Cache-Control"] == "no-store"
    assert response["Content-Disposition"] == 'attachment; filename="tibatrace-opening-stocktake-upload-pharmacy.csv"'
    rows = sheet(response)
    assert len(rows) == 33
    assert set(rows[0]) == {"item_id", "expected_updated_at", "item_code", "item_name", "sales_unit", "item_kind", "batch_number", "expiry_date", "counted_quantity", "counted_on", "notes"}
    assert all(not row[key] for row in rows for key in ("batch_number", "expiry_date", "counted_quantity", "counted_on", "notes"))
    reviewed = next(row for row in rows if row["item_id"] == str(items[2].pk))
    assert reviewed["sales_unit"] == "box" and reviewed["item_kind"] == "SUPPLY"
    assert any(row["item_code"] == "ITEM-003" for row in rows)
    payload["rows"] = [{**payload["rows"][0], "item_code":"NEXT-001"}]
    second = post(client, tenant, payload)
    assert len(sheet(client.get(TEMPLATE_URL, HTTP_X_TENANT_ID=str(tenant.pk)))) == 34
    assert len(sheet(client.get(TEMPLATE_URL, {"import_id":second.data["import_id"]}, HTTP_X_TENANT_ID=str(tenant.pk)))) == 1
    listing = client.get("/api/medicines/initial-setup/", HTTP_X_TENANT_ID=str(tenant.pk))
    assert listing.data["count"] == 36 and len(listing.data["results"]) == 25
    assert {batch["id"] for batch in listing.data["imports"]} == {first.data["import_id"], second.data["import_id"]}
    assert next(batch for batch in listing.data["imports"] if batch["id"] == first.data["import_id"])["item_count"] == 35
    assert listing.data["results"][0]["import_id"] and listing.data["results"][0]["source_date"] == "2026-10-09"


@pytest.mark.django_db
def test_template_cannot_cross_tenants_and_neutralises_spreadsheet_formulas(upload_data):
    tenant, actor, client, payload = upload_data
    payload["rows"][0].update(item_code="=COMMAND()", item_name=" +SUM(1,2)", sales_unit="@formula")
    payload["dry_run"] = False
    imported = post(client, tenant, payload)
    rows = sheet(client.get(TEMPLATE_URL, HTTP_X_TENANT_ID=str(tenant.pk)))
    assert rows[0]["item_code"].startswith("'=") and rows[0]["item_name"].startswith("'+")
    assert rows[0]["sales_unit"].startswith("'@")
    other = Tenant.objects.create(name="Other", slug="isolated-upload")
    assert sheet(client.get(TEMPLATE_URL, HTTP_X_TENANT_ID=str(other.pk))) == []
    for import_id in (imported.data["import_id"], str(uuid4()), "invalid"):
        assert client.get(TEMPLATE_URL, {"import_id":import_id}, HTTP_X_TENANT_ID=str(other.pk)).status_code == 404
    assert LegacyCatalogueItem.all_objects.get().source_name == "+SUM(1,2)"


@pytest.mark.django_db
def test_csv_accept_header_downloads_attachment_and_api_errors_stay_json(upload_data):
    tenant, actor, client, payload = upload_data
    payload["dry_run"] = False
    assert post(client, tenant, payload).data["created"] == 1
    response = client.get(TEMPLATE_URL, HTTP_X_TENANT_ID=str(tenant.pk), HTTP_ACCEPT="text/csv")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert sheet(response)[0]["item_code"] == "ITEM-001"
    refused = client.get(TEMPLATE_URL, HTTP_ACCEPT="text/csv")
    assert refused.status_code == 403
    assert refused["Content-Type"] == "application/json"
    assert "explicit tenant" in refused.json()["detail"]


@pytest.mark.django_db
def test_source_data_date_cannot_be_future(upload_data):
    tenant, actor, client, payload = upload_data
    payload.update(source_date=(timezone.localdate() + timedelta(days=1)).isoformat(), dry_run=False)
    response = post(client, tenant, payload)
    assert response.status_code == 400 and "source_date" in response.data
    assert not LegacyCatalogueImport.all_objects.exists()


@pytest.mark.django_db
def test_authorised_tenant_operator_can_import_and_download_only_own_items(upload_data):
    tenant, actor, client, payload = upload_data
    operator = get_user_model().objects.create_user(username="tenant-inventory-manager", tenant=tenant)
    role = Role.all_objects.create(tenant=tenant, code="inventory-manager", name="Inventory manager", capabilities=["inventory.manage"])
    UserRole.all_objects.create(tenant=tenant, user=operator, role=role)
    other = Tenant.objects.create(name="Other tenant", slug="other-tenant-items")
    client.force_authenticate(user=operator)
    preview = client.post(UPLOAD_URL, payload, format="json")
    assert preview.status_code == 200 and preview.data["valid"] is True
    payload["dry_run"] = False
    applied = client.post(UPLOAD_URL, payload, format="json")
    assert applied.status_code == 200 and applied.data["created"] == 1
    exported = client.get(TEMPLATE_URL, {"import_id": applied.data["import_id"]}, HTTP_ACCEPT="text/csv")
    assert exported.status_code == 200 and len(sheet(exported)) == 1
    assert post(client, other, payload).status_code == 403
    assert client.get(TEMPLATE_URL, HTTP_X_TENANT_ID=str(other.pk), HTTP_ACCEPT="text/csv").status_code == 403
    assert not LegacyCatalogueItem.all_objects.filter(tenant=other).exists()
