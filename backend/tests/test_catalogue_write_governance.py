"""Can the product master and the sales surfaces be written without a service?

The medicines viewsets were ModelViewSets. That made the product master -- the
table every dispensing decision resolves against -- writable by POST, PATCH and
DELETE from any authenticated caller, with no service, no approval and no audit
trail. Sales and customers had the same shape as procurement did before it was
corrected: service actions for the legitimate transitions, and a generic PATCH
sitting next to them that wrote the same columns without the checks.

Reachability is asserted first. A 405 on a route that 404s for everyone would
pass a "writes are blocked" test while proving nothing.

Pricing is deliberately still writable; see the last class.
"""
import pytest
from rest_framework.test import APIClient

from apps.customers.models import Customer
from apps.identity.models import User
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    Manufacturer,
    PackageDefinition,
)
from apps.tenancy.models import Tenant

PASSWORD = "governance-password-long"


@pytest.fixture(autouse=True)
def clear_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Gov Tenant", slug="gov-tenant")
    User.objects.create_user(username="gov-user", password=PASSWORD, tenant=tenant)
    manufacturer = Manufacturer.all_objects.create(
        tenant=tenant, code="MF-G", legal_name="Gov Pharma"
    )
    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    pack = PackageDefinition.objects.get_or_create(
        code="PK-G", defaults={"description": "Pack", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code="CMP-G", canonical_name="Metformin 500mg", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code="MP-G", brand_name="Glucophage",
        clinical_product=clinical, manufacturer=manufacturer,
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-G", display_name="Glucophage 500mg",
        manufactured_product=manufactured, package_definition=pack,
    )
    customer = Customer.all_objects.create(
        tenant=tenant, customer_number="CUS-G", legal_name="Retail Buyer Ltd",
        customer_type="RETAIL",
    )
    client = APIClient()
    assert client.post(
        "/api/identity/session/",
        {"username": "gov-user", "password": PASSWORD}, format="json",
    ).status_code == 200
    return {
        "tenant": tenant, "sku": sku, "clinical": clinical,
        "customer": customer, "client": client,
    }


class TestTheseRoutesAreReachable:
    """Otherwise every assertion below passes for the wrong reason."""

    def test_the_sku_detail_route_resolves(self, world):
        response = world["client"].get(f"/api/medicines/skus/{world['sku'].pk}/")
        assert response.status_code == 200
        assert response.json()["sku_code"] == "SKU-G"

    def test_the_customer_detail_route_resolves(self, world):
        response = world["client"].get(
            f"/api/customers/customers/{world['customer'].pk}/"
        )
        assert response.status_code == 200


class TestTheProductMasterIsNotWritable:
    def test_a_sku_cannot_be_patched(self, world):
        response = world["client"].patch(
            f"/api/medicines/skus/{world['sku'].pk}/",
            {"display_name": "Renamed by PATCH"}, format="json",
        )
        world["sku"].refresh_from_db()
        assert response.status_code in (403, 405)
        assert world["sku"].display_name == "Glucophage 500mg"

    def test_a_sku_cannot_be_deleted(self, world):
        # A SKU is referenced by ledger entries, receipts and dispensing lines.
        # Removing the row does not remove the history that points at it.
        response = world["client"].delete(f"/api/medicines/skus/{world['sku'].pk}/")
        assert response.status_code in (403, 405)
        assert CommercialSKU.all_objects.filter(pk=world["sku"].pk).exists()

    def test_a_sku_cannot_be_created(self, world):
        before = CommercialSKU.all_objects.count()
        response = world["client"].post(
            "/api/medicines/skus/",
            {"sku_code": "SKU-SNEAK", "display_name": "Unapproved"}, format="json",
        )
        assert response.status_code in (403, 405)
        assert CommercialSKU.all_objects.count() == before

    def test_a_clinical_product_cannot_be_patched(self, world):
        response = world["client"].patch(
            f"/api/medicines/clinical-products/{world['clinical'].pk}/",
            {"canonical_name": "Something else"}, format="json",
        )
        world["clinical"].refresh_from_db()
        assert response.status_code in (403, 405)
        assert world["clinical"].canonical_name == "Metformin 500mg"


class TestServiceActionsStillWork:
    """Blocking the generic write must not block the governed path."""

    def test_the_activate_action_is_still_routed(self, world):
        response = world["client"].post(
            f"/api/medicines/clinical-products/{world['clinical'].pk}/activate/"
        )
        # It runs the service. Whether the service permits the transition is its
        # business; what matters here is that the route exists and is not a 405.
        assert response.status_code != 405


class TestCustomersAreNotWritable:
    def test_a_customer_cannot_be_patched(self, world):
        response = world["client"].patch(
            f"/api/customers/customers/{world['customer'].pk}/",
            {"legal_name": "Renamed"}, format="json",
        )
        world["customer"].refresh_from_db()
        assert response.status_code in (403, 405)
        assert world["customer"].legal_name == "Retail Buyer Ltd"


class TestPricingIsStillWritableOnPurpose:
    """The one surface left open, and the reason is now established.

    PriceListEntry is the live business-to-business price table -- price_line in
    apps/sales/services.py bills every quotation and sales-order line from it,
    so closing it would stop price maintenance.

    The test exists so the exception reads as deliberate rather than as an
    oversight, and so that closing it later has to be an edit to a test that
    says why.
    """

    def test_the_price_list_route_still_accepts_writes(self, world):
        response = world["client"].post(
            "/api/sales/price-lists/", {"name": "Probe"}, format="json"
        )
        assert response.status_code != 405, (
            "Pricing has been made read-only, which stops B2B price "
            "maintenance. See docs/PRICING_AUTHORITY_DECISION.md."
        )
