from copy import deepcopy
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.medicines.models import CommercialSKU, Medicine
from apps.medicines.onboarding import import_source
from apps.medicines.onboarding_models import LegacyCatalogueImport, LegacyCatalogueItem
from apps.tenancy.models import Tenant


@pytest.fixture
def setup_data(db):
    tenant = Tenant.objects.create(name="Source Pharmacy", slug="source-pharmacy")
    actor = get_user_model().objects.create_user(username="source-operator", is_platform_admin=True)
    payload = {"tenant_slug":tenant.slug, "tenant_name":tenant.name, "import_code":"PDF-20261009-V1",
        "source_date":"2026-10-09", "expected_rows":1, "provenance":{"files":[{"sha256":"a" * 64}]},
        "items":[{"source_key":"CODE:1", "source_row":1, "legacy_code":"1", "proposed_sku_code":"TE-0001",
            "source_name":"Paracetamol 500mg", "source_uom":"pcs", "source_cost":"0.47", "source_price":"2.00",
            "source_quantity":"30", "source_product":{"file":"Products.pdf", "page":1},
            "source_stock":{"file":"Stock.pdf", "page":1}, "source_issues":[]}]}
    return tenant, actor, payload


@pytest.mark.django_db
def test_stage_is_dry_run_by_default_and_retry_preserves_manager_work(setup_data):
    tenant, actor, payload = setup_data
    preview = import_source(tenant=tenant, actor=actor, payload=payload)
    assert preview["ready_to_stage"] == 1
    assert not LegacyCatalogueImport.all_objects.exists()
    import_source(tenant=tenant, actor=actor, payload=payload, apply=True)
    item = LegacyCatalogueItem.all_objects.get()
    item.review = {"notes":"Manager has started"}
    item.save()
    retry = import_source(tenant=tenant, actor=actor, payload=payload, apply=True)
    assert retry["existing"] == 1
    item.refresh_from_db()
    assert item.review["notes"] == "Manager has started"
    assert not CommercialSKU.all_objects.exists()
    assert not Medicine.all_objects.exists()


@pytest.mark.django_db
def test_bad_count_duplicate_or_wrong_tenant_does_not_partially_import(setup_data):
    tenant, actor, payload = setup_data
    for mutate in (lambda p:p.update(expected_rows=2), lambda p:p.update(tenant_slug="other"),
                   lambda p:p.update(items=p["items"]*2, expected_rows=2)):
        invalid = deepcopy(payload)
        mutate(invalid)
        with pytest.raises(ValidationError):
            import_source(tenant=tenant, actor=actor, payload=invalid, apply=True)
        assert not LegacyCatalogueItem.all_objects.exists()


@pytest.mark.django_db
def test_review_is_tenant_scoped_permissioned_and_optimistic(setup_data):
    tenant, actor, payload = setup_data
    import_source(tenant=tenant, actor=actor, payload=payload, apply=True)
    item = LegacyCatalogueItem.all_objects.get()
    reader = get_user_model().objects.create_user(username="reader", tenant=tenant)
    other = Tenant.objects.create(name="Other", slug="other")
    client = APIClient()
    client.force_authenticate(user=actor)
    listing = client.get("/api/medicines/initial-setup/", HTTP_X_TENANT_ID=str(tenant.pk))
    assert listing.status_code == 200 and listing.data["summary"]["total"] == 1
    assert listing.data["results"][0]["saleable"] is False
    url = f"/api/medicines/initial-setup/{item.pk}/review/"
    body = {"expected_updated_at":item.updated_at.isoformat(), "review":{"notes":"Unit check pending"}}
    assert client.post(url, body, format="json", HTTP_X_TENANT_ID=str(other.pk)).status_code == 404
    client.force_authenticate(user=reader)
    assert client.post(url, body, format="json").status_code == 403
    client.force_authenticate(user=actor)
    saved = client.post(url, body, format="json", HTTP_X_TENANT_ID=str(tenant.pk))
    assert saved.status_code == 200 and saved.data["status"] == "IN_PROGRESS"
    assert client.post(url, body, format="json", HTTP_X_TENANT_ID=str(tenant.pk)).status_code == 409
    item.refresh_from_db()
    assert item.source_price == 2
    assert item.review["notes"] == "Unit check pending"
    assert client.patch(url, {}, format="json", HTTP_X_TENANT_ID=str(tenant.pk)).status_code == 405


@pytest.mark.django_db
def test_batch_validation_readiness_and_no_activation(setup_data):
    tenant, actor, payload = setup_data
    import_source(tenant=tenant, actor=actor, payload=payload, apply=True)
    item = LegacyCatalogueItem.all_objects.get()
    Medicine.all_objects.create(is_global=True, code="PH100", generic_name="Reference", status="INACTIVE", source="test", source_version="1")
    client = APIClient()
    client.force_authenticate(user=actor)
    url = f"/api/medicines/initial-setup/{item.pk}/review/"
    review = {"item_kind":"MEDICINE", "sales_unit":"tablet", "pack_description":"100 tablets, sold per tablet",
        "confirmed_price":"2", "confirmed_cost":"1", "counted_quantity":"30", "counted_on":timezone.localdate().isoformat(),
        "tax_category":"EXEMPT", "master_catalogue_code":"PH100", "batches":[]}
    def post():
        item.refresh_from_db()
        return client.post(url, {"expected_updated_at":item.updated_at.isoformat(), "review":review}, format="json", HTTP_X_TENANT_ID=str(tenant.pk))
    missing = post()
    assert missing.status_code == 200
    assert "Actual batches and expiry dates" in missing.data["missing_details"]
    review["batches"] = [{"batch_number":"LOT-A", "expiry_date":(timezone.localdate()+timedelta(days=365)).isoformat(), "quantity":"29"}]
    assert "Batch quantities must equal physical count" in post().data["missing_details"]
    review["batches"][0]["quantity"] = "30"
    completed = post()
    assert completed.status_code == 200 and completed.data["status"] == "DETAILS_COMPLETE"
    assert completed.data["saleable"] is False and not CommercialSKU.all_objects.exists()
    review["batches"][0]["expiry_date"] = timezone.localdate().isoformat()
    assert "Expired stock must be separated; it cannot be released" in post().data["missing_details"]
    review["batches"][0]["quantity"] = "-1"
    assert post().status_code == 400
    review["batches"] = []
    review["master_catalogue_code"] = "NONEXISTENT"
    assert post().status_code == 400
