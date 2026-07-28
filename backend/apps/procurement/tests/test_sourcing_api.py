"""The sourcing cycle over HTTP.

The services existed with no route, so HQ could not run a tender at all. These
assert the whole cycle works through the API and, more importantly, that the
controls survive the trip: a refusal that only holds when a service is called
directly is not a control.
"""
import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.procurement.models import Supplier
from apps.tenancy.models import Tenant

PASSWORD = "sourcing-api-password"


@pytest.fixture(autouse=True)
def clear_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="RFQ Tenant", slug="rfq-api-tenant")
    buyer = User.objects.create_user(
        username="rfq-buyer", password=PASSWORD, tenant=tenant
    )
    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    pack = PackageDefinition.objects.get_or_create(
        code="PK-API", defaults={"description": "Pack", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code="CMP-API", canonical_name="Ibuprofen 400mg", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code="MP-API", brand_name="Brufen", clinical_product=clinical
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-API", display_name="Brufen 400mg",
        manufactured_product=manufactured, package_definition=pack,
    )
    client = APIClient()
    assert client.post(
        "/api/identity/session/",
        {"username": "rfq-buyer", "password": PASSWORD}, format="json",
    ).status_code == 200
    return {"tenant": tenant, "buyer": buyer, "sku": sku, "client": client}


def a_supplier(world, code, status=Supplier.Status.APPROVED):
    return Supplier.all_objects.create(
        tenant=world["tenant"], supplier_code=code,
        legal_name=f"{code} Ltd", status=status,
    )


def raise_rfq(world, days=7):
    response = world["client"].post(
        "/api/procurement/rfqs/",
        {
            "title": "Analgesics restock",
            "closing_date": (timezone.localdate() + datetime.timedelta(days=days)).isoformat(),
            "lines": [{"sku_id": str(world["sku"].pk), "requested_quantity": 200}],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.json()


def quote(world, rfq, supplier, unit_cost, reference=None):
    return world["client"].post(
        f"/api/procurement/rfqs/{rfq['id']}/quotations/submit/",
        {
            "supplier_id": str(supplier.pk),
            "quotation_reference": reference or f"Q-{supplier.supplier_code}",
            "valid_until": (
                timezone.localdate() + datetime.timedelta(days=60)
            ).isoformat(),
            "lines": [{
                "sku_id": str(world["sku"].pk),
                "quoted_quantity": 200,
                "quoted_unit_cost": str(Decimal(unit_cost)),
            }],
        },
        format="json",
    )


class TestTheCycleRunsOverHttp:
    def test_a_tender_can_be_raised_quoted_and_awarded(self, world):
        rfq = raise_rfq(world)
        assert rfq["status"] == "OPEN"
        assert rfq["quotation_count"] == 0

        cheap = quote(world, rfq, a_supplier(world, "SUP-A"), "10.00")
        assert cheap.status_code == 201, cheap.content
        # Summed from the lines, not taken from the caller.
        assert Decimal(cheap.json()["total_quoted_cost"]) == Decimal("2000.00")

        quote(world, rfq, a_supplier(world, "SUP-B"), "12.00")

        awarded = world["client"].post(
            f"/api/procurement/rfqs/{rfq['id']}/award/",
            {"quotation_id": cheap.json()["id"]}, format="json",
        )
        assert awarded.status_code == 200, awarded.content
        assert awarded.json()["status"] == "AWARDED"

    def test_quotations_are_listed_cheapest_first(self, world):
        """The comparison an award is judged on is what the screen leads with."""
        rfq = raise_rfq(world)
        quote(world, rfq, a_supplier(world, "SUP-DEAR"), "20.00")
        quote(world, rfq, a_supplier(world, "SUP-CHEAP"), "9.00")

        listed = world["client"].get(
            f"/api/procurement/rfqs/{rfq['id']}/quotations/"
        ).json()
        assert [row["supplier_code"] for row in listed] == ["SUP-CHEAP", "SUP-DEAR"]


class TestTheControlsSurviveTheTrip:
    def test_a_quotation_from_another_tender_is_refused_by_name(self, world):
        """The control this module exists for.

        The view deliberately does not filter the quotation by RFQ: doing so
        would turn the refusal into a generic "not found" and hide what was
        actually attempted.
        """
        rfq = raise_rfq(world)
        quote(world, rfq, a_supplier(world, "SUP-OWN"), "10.00")

        other = raise_rfq(world)
        outsider = quote(world, other, a_supplier(world, "SUP-OTHER"), "1.00")

        response = world["client"].post(
            f"/api/procurement/rfqs/{rfq['id']}/award/",
            {"quotation_id": outsider.json()["id"]}, format="json",
        )
        assert response.status_code == 400
        assert "different request for quotation" in str(response.json())

    def test_awarding_above_the_lowest_quote_needs_a_reason(self, world):
        rfq = raise_rfq(world)
        quote(world, rfq, a_supplier(world, "SUP-LOW"), "10.00")
        dearer = quote(world, rfq, a_supplier(world, "SUP-HIGH"), "18.00")

        refused = world["client"].post(
            f"/api/procurement/rfqs/{rfq['id']}/award/",
            {"quotation_id": dearer.json()["id"]}, format="json",
        )
        assert refused.status_code == 400
        assert "stated reason" in str(refused.json())

        accepted = world["client"].post(
            f"/api/procurement/rfqs/{rfq['id']}/award/",
            {
                "quotation_id": dearer.json()["id"],
                "justification": "Only supplier with cold chain to Kisumu.",
            },
            format="json",
        )
        assert accepted.status_code == 200

    def test_a_suspended_supplier_cannot_quote_over_http(self, world):
        rfq = raise_rfq(world)
        suspended = a_supplier(world, "SUP-SUSP", Supplier.Status.SUSPENDED)
        response = quote(world, rfq, suspended, "5.00")
        assert response.status_code == 400
        assert "cannot quote" in str(response.json())

    def test_a_closing_date_in_the_past_is_refused_over_http(self, world):
        response = world["client"].post(
            "/api/procurement/rfqs/",
            {
                "title": "Backdated",
                "closing_date": (
                    timezone.localdate() - datetime.timedelta(days=1)
                ).isoformat(),
                "lines": [{"sku_id": str(world["sku"].pk), "requested_quantity": 10}],
            },
            format="json",
        )
        assert response.status_code == 400
        assert "past" in str(response.json())


class TestTheSurfaceStaysGoverned:
    def test_a_tender_cannot_be_awarded_by_patching_its_status(self, world):
        """Awarding is the decision this module governs.

        It must not be reachable by writing a column.
        """
        rfq = raise_rfq(world)
        response = world["client"].patch(
            f"/api/procurement/rfqs/{rfq['id']}/",
            {"status": "AWARDED"}, format="json",
        )
        assert response.status_code in (403, 405)

        current = world["client"].get(f"/api/procurement/rfqs/{rfq['id']}/").json()
        assert current["status"] == "OPEN"

    def test_an_anonymous_caller_cannot_read_tenders(self, world):
        assert APIClient().get("/api/procurement/rfqs/").status_code in (401, 403)
