import hashlib
import json

import pytest

from apps.medicines.government_catalogue import (
    ETCD_PRODUCT_IDENTIFIER_SYSTEM,
    PPB_REGISTRATION_IDENTIFIER_SYSTEM,
    build_government_catalogue_plan,
    import_government_catalogue,
    load_government_catalogue,
)
from apps.medicines.models import Medicine, MedicineIdentifier


def catalogue_product(**overrides):
    product = {
        "etcd_product_id": "PH100",
        "generic_concept_id": 228,
        "generic_concept_code": "GE10228",
        "ppb_registration_code": "PPB/100",
        "brand_display_name": "Example Brand 5 mg Oral Tablet",
        "generic_display_name": "Example 5 mg Oral Tablet",
        "brand_name": "Example Brand",
        "generic_name": "Example",
        "strength_amount": "5",
        "strength_unit": "mg",
        "route_description": "Oral",
        "route_id": 25,
        "route_code": "RT10025",
        "form_description": "Tablet",
        "form_id": 501,
        "form_code": "DF10501",
        "active_component_id": 1259,
        "active_component_code": "AC11259",
        "level_of_use": "4",
        "keml_status": "Yes",
        "updation_date": "2026-07-14T03:46:53.759Z",
        "manufacture_name": "Example Manufacturer",
    }
    product.update(overrides)
    return product


def test_plan_quarantines_missing_and_conflicting_etcd_product_ids():
    products = [
        catalogue_product(),
        catalogue_product(etcd_product_id="PH200", brand_name="One"),
        catalogue_product(etcd_product_id="PH200", brand_name="Two"),
        catalogue_product(etcd_product_id=""),
    ]

    plan = build_government_catalogue_plan(products, "a" * 64)

    assert [record.etcd_product_id for record in plan.records] == ["PH100"]
    assert plan.report()["quarantine_counts"] == {
        "conflicting_etcd_product_id": 2,
        "missing_etcd_product_id": 1,
    }


def test_plan_quarantines_invalid_update_dates():
    plan = build_government_catalogue_plan(
        [catalogue_product(updation_date="not-a-date")], "a" * 64
    )

    assert not plan.records
    assert plan.report()["quarantine_counts"] == {"invalid_updation_date": 1}


@pytest.mark.django_db
def test_import_preserves_government_codes_and_requires_activation_review():
    plan = build_government_catalogue_plan([catalogue_product()], "b" * 64)

    result = import_government_catalogue(plan)

    medicine = Medicine.all_objects.get(code="PH100", is_global=True, tenant__isnull=True)
    assert result.created == 1
    assert medicine.status == Medicine.STATUS_INACTIVE
    assert medicine.licence_identifier == "PPB/100"
    assert medicine.metadata["generic_concept"]["code"] == "GE10228"
    assert medicine.metadata["route"]["code"] == "RT10025"
    assert medicine.metadata["dose_form"]["code"] == "DF10501"
    assert medicine.metadata["keml"] == {"status": "Yes", "level_of_use": "4"}
    assert MedicineIdentifier.objects.filter(
        medicine=medicine,
        system=ETCD_PRODUCT_IDENTIFIER_SYSTEM,
        value="PH100",
    ).exists()
    assert MedicineIdentifier.objects.filter(
        medicine=medicine,
        system=PPB_REGISTRATION_IDENTIFIER_SYSTEM,
        value="PPB/100",
    ).exists()


@pytest.mark.django_db
def test_import_is_idempotent_and_omits_ambiguous_ppb_identifiers():
    plan = build_government_catalogue_plan(
        [
            catalogue_product(etcd_product_id="PH100", ppb_registration_code="PPB/DUPLICATE"),
            catalogue_product(etcd_product_id="PH101", ppb_registration_code="PPB/DUPLICATE"),
        ],
        "c" * 64,
    )

    first = import_government_catalogue(plan)
    second = import_government_catalogue(plan)

    assert first.created == 2
    assert first.ppb_identifiers_omitted == 2
    assert second.created == 0
    assert second.updated == 2
    assert Medicine.all_objects.filter(is_global=True, source="Kenya eTCD Product Catalogue").count() == 2
    assert not MedicineIdentifier.objects.filter(
        system=PPB_REGISTRATION_IDENTIFIER_SYSTEM,
        value="PPB/DUPLICATE",
    ).exists()


def test_loader_requires_a_successful_catalogue_payload(tmp_path):
    payload = {"IsSuccess": True, "Data": {"products": [catalogue_product()]}}
    catalogue_path = tmp_path / "catalogue.json"
    raw_catalogue = json.dumps(payload).encode("utf-8")
    catalogue_path.write_bytes(raw_catalogue)

    plan = load_government_catalogue(catalogue_path)

    assert plan.source_checksum == hashlib.sha256(raw_catalogue).hexdigest()
    assert len(plan.records) == 1
