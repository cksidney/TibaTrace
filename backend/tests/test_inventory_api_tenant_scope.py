"""The inventory API: does it answer, and only for one tenant?

Same fault as the medicines catalogue had. Every viewset declared
`queryset = Model.objects.all()` as a class attribute; `objects` is the
tenant-strict manager and a class attribute is evaluated once at import, when
there is no tenant context, so it was frozen as `.none()` for the life of the
process. Stock levels, batches and the ledger returned nothing to everyone.

Reachability is asserted before isolation, because a 200 with an empty list
passes an isolation test for the wrong reason -- unreachable is not the same as
scoped.
"""
from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.inventory.models import InventoryBatch, InventoryLocation, InventoryReservation
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.tenancy.models import Tenant

PASSWORD = "inventory-scope-password"


@pytest.fixture(autouse=True)
def clear_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def build(slug, batch_number):
    tenant = Tenant.objects.create(name=slug.title(), slug=slug)
    org = Organization.all_objects.create(tenant=tenant, code=f"O-{slug[:3]}", name="Org")
    branch = Location.all_objects.create(
        tenant=tenant, organization=org, code=f"B-{slug[:3]}", name="Branch"
    )
    user = User.objects.create_user(
        username=f"{slug}-user", password=PASSWORD, tenant=tenant
    )
    location = InventoryLocation.all_objects.create(
        tenant=tenant, branch=branch, location_code=f"LOC-{slug[:3]}",
        name="Main store", location_type=InventoryLocation.LocationType.STORE,
    )
    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    pack = PackageDefinition.objects.get_or_create(
        code="PK-10", defaults={"description": "10s", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code=f"CMP-{slug[:3]}", canonical_name="Ibuprofen 400mg",
        dose_form=dose,
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code=f"MP-{slug[:3]}", brand_name="Brufen",
        clinical_product=clinical,
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code=f"SKU-{slug[:3]}", display_name="Brufen 400mg",
        manufactured_product=manufactured, package_definition=pack,
    )
    batch = InventoryBatch.all_objects.create(
        tenant=tenant, sku=sku, manufactured_product=manufactured,
        manufacturer_batch_number=batch_number,
        expiry_date=date.today() + timedelta(days=200),
    )
    reservation = InventoryReservation.all_objects.create(
        tenant=tenant,
        branch=branch,
        source_location=location,
        sku=sku,
        batch=batch,
        requested_quantity="2.0000",
        allocated_quantity="1.0000",
        unit="tablet",
        purpose="API scope test",
        idempotency_key=f"reservation-{slug}",
    )
    return {
        "tenant": tenant,
        "user": user,
        "location": location,
        "batch": batch,
        "reservation": reservation,
    }


@pytest.fixture
def nairobi(db):
    return build("nrb-stock", "BATCH-NRB-1")


@pytest.fixture
def mombasa(db):
    return build("msa-stock", "BATCH-MSA-1")


def client_for(world):
    client = APIClient()
    response = client.post(
        "/api/identity/session/",
        {"username": world["user"].username, "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200, response.content
    return client


def rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


class TestReachable:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/inventory/locations/",
            "/api/inventory/batches/",
            "/api/inventory/reservations/",
        ],
    )
    def test_a_collection_returns_the_tenants_rows(self, nairobi, path):
        response = client_for(nairobi).get(path)
        assert response.status_code == 200
        assert len(rows(response)) >= 1, (
            f"{path} is empty for a tenant that has rows. The class-attribute "
            "queryset was frozen empty at import, when no tenant context exists."
        )

    def test_collections_include_hq_display_fields(self, nairobi):
        client = client_for(nairobi)

        location = rows(client.get("/api/inventory/locations/"))[0]
        assert location["location_code"] == "LOC-nrb"
        assert location["branch_name"] == "Branch"
        assert "cold_chain_capability" in location

        batch = rows(client.get("/api/inventory/batches/"))[0]
        assert batch["sku_code"] == "SKU-nrb"

        reservation = rows(client.get("/api/inventory/reservations/"))[0]
        assert reservation["sku_code"] == "SKU-nrb"
        assert reservation["location_name"] == "Main store"
        assert reservation["batch_number"] == "BATCH-NRB-1"


class TestIsolation:
    def test_batches_exclude_another_tenants_stock(self, nairobi, mombasa):
        response = client_for(nairobi).get("/api/inventory/batches/")
        numbers = {r.get("manufacturer_batch_number") for r in rows(response)}
        assert "BATCH-NRB-1" in numbers
        assert "BATCH-MSA-1" not in numbers

    def test_another_tenants_batch_detail_is_not_readable(self, nairobi, mombasa):
        response = client_for(nairobi).get(
            f"/api/inventory/batches/{mombasa['batch'].pk}/"
        )
        assert response.status_code == 404

    def test_an_anonymous_caller_gets_nothing(self, nairobi):
        response = APIClient().get("/api/inventory/batches/")
        assert response.status_code in (401, 403) or len(rows(response)) == 0
