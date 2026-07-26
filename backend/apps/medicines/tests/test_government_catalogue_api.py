import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.medicines.government_catalogue import SOURCE_NAME
from apps.medicines.models import Medicine, TenantCatalogueProduct
from apps.tenancy.models import Tenant


def government_medicine(code, generic_name, **overrides):
    values = {
        "tenant": None,
        "is_global": True,
        "code": code,
        "generic_name": generic_name,
        "brand_name": "",
        "dosage_form": "Tablet",
        "strength": "500 mg",
        "status": Medicine.STATUS_INACTIVE,
        "source": SOURCE_NAME,
        "source_version": "sha256:test;updated:2026-07-14",
        "licence_identifier": "",
        "metadata": {
            "catalogue_standard": "KE-ETCD",
            "keml": {"status": "Yes", "level_of_use": "4"},
            "manufacturer_name": "Kenya Pharma",
            "route": {"display_name": "Oral"},
            "source_updated_at": "2026-07-14T12:00:00Z",
        },
    }
    values.update(overrides)
    return Medicine.all_objects.create(**values)


@pytest.mark.django_db
def test_government_catalogue_is_authenticated_searchable_and_paginated():
    user = get_user_model().objects.create_user(
        username="catalogue-reader",
        password="catalogue-password-long-enough",
        is_platform_admin=True,
    )
    government_medicine("PH100", "Diazepam", brand_name="Valium")
    government_medicine(
        "PH101",
        "Paracetamol",
        metadata={
            "catalogue_standard": "KE-ETCD",
            "keml": {"status": "No", "level_of_use": "2"},
            "manufacturer_name": "Acme Health",
            "route": {"display_name": "Oral"},
            "source_updated_at": "2026-07-14T12:00:00Z",
        },
    )
    Medicine.all_objects.create(
        tenant=None,
        is_global=True,
        code="OTHER-1",
        generic_name="Not government data",
        status=Medicine.STATUS_ACTIVE,
        source="Another catalogue",
        source_version="1",
    )

    assert APIClient().get("/api/medicines/government-catalogue/").status_code in (401, 403)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get(
        "/api/medicines/government-catalogue/",
        {"q": "valium", "keml_status": "Yes", "level_of_use": "4", "page_size": 10},
    )

    assert response.status_code == 200
    assert response.data["source"] == SOURCE_NAME
    assert response.data["catalogue_count"] == 2
    assert response.data["count"] == 1
    assert response.data["page"] == 1
    assert response.data["page_size"] == 10
    assert response.data["results"] == [
        {
            "id": str(Medicine.all_objects.get(code="PH100").id),
            "code": "PH100",
            "generic_name": "Diazepam",
            "brand_name": "Valium",
            "dosage_form": "Tablet",
            "strength": "500 mg",
            "route": "Oral",
            "licence_identifier": "",
            "manufacturer_name": "Kenya Pharma",
            "keml_status": "Yes",
            "level_of_use": "4",
            "status": "INACTIVE",
            "catalogue_standard": "KE-ETCD",
            "source_updated_at": "2026-07-14T12:00:00Z",
            "selected": False,
            "selection_status": "",
            "tenant_code": "",
        }
    ]


@pytest.mark.django_db
def test_government_catalogue_bounds_page_size():
    user = get_user_model().objects.create_user(
        username="catalogue-paging",
        password="catalogue-password-long-enough",
        is_platform_admin=True,
    )
    government_medicine("PH200", "Amoxicillin")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(
        "/api/medicines/government-catalogue/",
        {"page_size": 999},
    )

    assert response.status_code == 200
    assert response.data["page_size"] == 100


@pytest.mark.django_db
def test_tenant_selects_products_from_universal_catalogue_without_cross_tenant_leakage():
    user = get_user_model().objects.create_user(
        username="catalogue-platform-admin",
        password="catalogue-password-long-enough",
        is_platform_admin=True,
    )
    nairobi = Tenant.objects.create(name="Nairobi Pharmacy", slug="nairobi-pharmacy")
    mombasa = Tenant.objects.create(name="Mombasa Pharmacy", slug="mombasa-pharmacy")
    medicine = government_medicine("PH300", "Metformin")
    client = APIClient()
    client.force_authenticate(user=user)
    selection_url = f"/api/medicines/government-catalogue/{medicine.pk}/selection/"

    first = client.post(selection_url, HTTP_X_TENANT_ID=str(nairobi.pk))
    second = client.post(selection_url, HTTP_X_TENANT_ID=str(nairobi.pk))

    assert first.status_code == 201
    assert second.status_code == 200
    assert TenantCatalogueProduct.all_objects.filter(
        tenant=nairobi,
        master_medicine=medicine,
        status=TenantCatalogueProduct.STATUS_SELECTED,
    ).count() == 1

    nairobi_catalogue = client.get(
        "/api/medicines/government-catalogue/",
        {"selected_only": "true"},
        HTTP_X_TENANT_ID=str(nairobi.pk),
    )
    assert nairobi_catalogue.status_code == 200
    assert nairobi_catalogue.data["tenant_name"] == "Nairobi Pharmacy"
    assert nairobi_catalogue.data["selected_count"] == 1
    assert nairobi_catalogue.data["count"] == 1
    assert nairobi_catalogue.data["results"][0]["selected"] is True
    assert nairobi_catalogue.data["results"][0]["tenant_code"] == "PH300"

    mombasa_catalogue = client.get(
        "/api/medicines/government-catalogue/",
        {"selected_only": "true"},
        HTTP_X_TENANT_ID=str(mombasa.pk),
    )
    assert mombasa_catalogue.status_code == 200
    assert mombasa_catalogue.data["selected_count"] == 0
    assert mombasa_catalogue.data["count"] == 0

    removed = client.delete(selection_url, HTTP_X_TENANT_ID=str(nairobi.pk))
    assert removed.status_code == 200
    assert TenantCatalogueProduct.all_objects.get(
        tenant=nairobi,
        master_medicine=medicine,
    ).status == TenantCatalogueProduct.STATUS_REMOVED
