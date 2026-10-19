# ruff: noqa: F811
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from tests.test_hq_queue_completion import opening
from tests.test_pos_retail_transactions import world  # noqa: F401

from apps.medicines.onboarding import save_review
from apps.medicines.onboarding_discard import discard_import
from apps.medicines.onboarding_upload import import_item_upload

pytestmark = pytest.mark.django_db


def test_active_rows_survive_json_filter_and_discarded_codes_can_be_corrected(world):
    item, _, _ = opening(world)
    response = world["client"].get("/api/medicines/initial-setup/")
    assert response.status_code == 200 and response.data["count"] == 1
    assert len(response.data["imports"]) == 1
    discard_import(
        batch=item.import_batch, actor=world["operator"], reason="Owner discarded unverified source", expected_items=1
    )
    response = world["client"].get("/api/medicines/initial-setup/")
    assert response.status_code == 200 and response.data["count"] == 0
    assert response.data["imports"] == []
    corrected = [
        {
            "item_code": item.proposed_sku_code,
            "item_name": "Verified correct current item",
            "sales_unit": "pack",
            "item_kind": "MEDICINE",
            "cost_price": "20",
            "selling_price": "125",
            "tax_category": "STANDARD",
            "pack_description": "Verified selling pack",
        }
    ]
    result = import_item_upload(
        tenant=world["tenant"],
        actor=world["operator"],
        rows=corrected,
        source_date=timezone.localdate(),
        source_filename="corrected.csv",
        dry_run=False,
    )
    assert result["valid"] and result["created"] == 1, result
    assert world["client"].get("/api/medicines/initial-setup/").data["count"] == 1
    item.refresh_from_db()
    with pytest.raises(ValidationError, match="discarded"):
        save_review(item=item, actor=world["operator"], review={}, expected_updated_at=item.updated_at.isoformat())


def test_barcode_pack_configuration_validates_precision_and_tenant_identity(world):
    path = "/api/inventory/barcode-packs/"
    values = {"sku": str(world["sku"].pk), "barcode": "VERIFIED-PACK-5", "pack_conversion": "5", "is_active": True}
    response = world["client"].post(path, values, format="json")
    assert response.status_code == 200, response.data
    assert response.data["pack_conversion"] == "5.0000"
    assert world["client"].post(path, {**values, "pack_conversion": "-5"}, format="json").status_code == 400
    assert world["client"].post(path, {**values, "pack_conversion": "1.00001"}, format="json").status_code == 400
