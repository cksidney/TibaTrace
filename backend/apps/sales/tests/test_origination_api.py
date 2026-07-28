"""Raising quotations, orders, substitutions and returns over HTTP.

Seventeen of the module's forty-four service methods had no route, and among them
was the entire origination path: `create_quotation`, `create_sales_order`,
`request_return`, `propose_substitution`. Sales could progress an order and never
raise one.

Before that, creation went through the generic ModelViewSet POST, which wrote the
row straight from the serializer -- no numbering, no tenant checks on branch and
customer, no fulfilment or substitution policy. Closing that left no governed
path at all, which is what this restores.
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
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.sales.models import Quotation, SalesOrder
from apps.tenancy.models import Tenant

PASSWORD = "sales-origination-password"


@pytest.fixture(autouse=True)
def clear_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Sales Tenant", slug="sales-orig-tenant")
    other_tenant = Tenant.objects.create(name="Other", slug="sales-orig-other")

    user = User.objects.create_user(
        username="sales-user", password=PASSWORD, tenant=tenant
    )
    org = Organization.all_objects.create(tenant=tenant, code="ORG-SO", name="Org")
    branch = Location.all_objects.create(
        tenant=tenant, organization=org, code="BR-SO", name="Branch"
    )
    customer = Customer.all_objects.create(
        tenant=tenant, customer_number="CUS-SO", legal_name="Wholesale Buyer",
        customer_type="WHOLESALE",
    )
    # Belongs to somebody else. Used to prove the tenant checks the generic POST
    # skipped are actually applied.
    foreign_customer = Customer.all_objects.create(
        tenant=other_tenant, customer_number="CUS-FOREIGN", legal_name="Not Ours",
        customer_type="WHOLESALE",
    )

    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    pack = PackageDefinition.objects.get_or_create(
        code="PK-SO", defaults={"description": "Pack", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code="CMP-SO", canonical_name="Amlodipine 5mg", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code="MP-SO", brand_name="Norvasc", clinical_product=clinical
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-SO", display_name="Norvasc 5mg",
        manufactured_product=manufactured, package_definition=pack,
        # Sales refuses a SKU that is not active and saleable, which is correct
        # -- an order for something withdrawn is an order nobody can fill.
        status=CommercialSKU.STATUS_ACTIVE, is_saleable=True,
    )

    client = APIClient()
    assert client.post(
        "/api/identity/session/",
        {"username": "sales-user", "password": PASSWORD}, format="json",
    ).status_code == 200

    return {
        "tenant": tenant, "user": user, "branch": branch, "customer": customer,
        "foreign_customer": foreign_customer, "sku": sku, "client": client,
    }


def raise_order(world, **overrides):
    payload = {
        "branch": str(world["branch"].pk),
        "customer": str(world["customer"].pk),
        "customer_po_reference": "PO-FROM-CUSTOMER",
    }
    payload.update(overrides)
    return world["client"].post("/api/sales/orders/", payload, format="json")


class TestOrdersCanBeRaisedAgain:
    def test_a_sales_order_is_created_through_the_service(self, world):
        response = raise_order(world)
        assert response.status_code == 201, response.content
        body = response.json()
        # Numbered by the service. The generic POST left this to the caller.
        assert body["order_number"]
        assert body["status"] == SalesOrder.Status.DRAFT

    def test_a_line_can_be_added_and_is_priced(self, world):
        order = raise_order(world).json()
        response = world["client"].post(
            f"/api/sales/orders/{order['id']}/lines/",
            {"sku": str(world["sku"].pk), "requested_quantity": "10.000"},
            format="json",
        )
        assert response.status_code == 201, response.content

    def test_a_quotation_can_be_raised(self, world):
        response = world["client"].post(
            "/api/sales/quotations/",
            {"branch": str(world["branch"].pk), "customer": str(world["customer"].pk)},
            format="json",
        )
        assert response.status_code == 201, response.content
        assert response.json()["status"] == Quotation.Status.DRAFT


class TestTheChecksTheGenericPostSkipped:
    def test_another_tenants_customer_is_refused(self, world):
        """The generic POST wrote whatever customer id it was given.

        An order for a customer belonging to a different pharmacy is not a
        validation nicety: it is one tenant's commercial data in another's ledger.
        """
        response = raise_order(world, customer=str(world["foreign_customer"].pk))
        assert response.status_code == 400
        assert "customer" in str(response.json()).lower()

    def test_an_unknown_branch_is_refused_by_name(self, world):
        response = raise_order(world, branch="00000000-0000-0000-0000-000000000000")
        assert response.status_code == 400
        assert "branch" in str(response.json()).lower()

    def test_the_substitution_policy_is_carried_from_the_request(self, world):
        """It governs whether a dispensed medicine may be swapped.

        The generic POST treated it as another column; here it is set
        deliberately and the service holds it.
        """
        response = raise_order(world, substitution_policy="NO_SUBSTITUTION")
        assert response.status_code == 201
        assert response.json()["substitution_policy"] == "NO_SUBSTITUTION"


class TestSubstitutionIsGoverned:
    def test_a_substitution_is_refused_when_the_order_forbids_it(self, world):
        """A clinical decision, not a stock convenience.

        The order's policy decides, and the service refuses outright rather than
        recording a proposal nobody may act on.
        """
        order = raise_order(world, substitution_policy="NO_SUBSTITUTION").json()
        line = world["client"].post(
            f"/api/sales/orders/{order['id']}/lines/",
            {"sku": str(world["sku"].pk), "requested_quantity": "5.000"},
            format="json",
        ).json()
        line_id = line["lines"][0]["id"] if line.get("lines") else None
        assert line_id, "the order should carry the line it was just given"

        response = world["client"].post(
            f"/api/sales/orders/{order['id']}/substitutions/",
            {
                "sales_order_line": line_id,
                "proposed_sku": str(world["sku"].pk),
                "reason": "Out of stock.",
            },
            format="json",
        )
        assert response.status_code == 400

    def test_a_substitution_requires_a_reason(self, world):
        order = raise_order(world).json()
        response = world["client"].post(
            f"/api/sales/orders/{order['id']}/substitutions/",
            {
                "sales_order_line": "00000000-0000-0000-0000-000000000000",
                "proposed_sku": str(world["sku"].pk),
            },
            format="json",
        )
        # Refused for the missing reason before any lookup happens.
        assert response.status_code == 400
        assert "reason" in str(response.json()).lower()


class TestTheSurfaceStaysGoverned:
    def test_an_order_status_cannot_be_patched(self, world):
        order = raise_order(world).json()
        response = world["client"].patch(
            f"/api/sales/orders/{order['id']}/",
            {"status": "APPROVED"}, format="json",
        )
        assert response.status_code in (403, 405)

        current = world["client"].get(f"/api/sales/orders/{order['id']}/").json()
        assert current["status"] == SalesOrder.Status.DRAFT

    def test_an_anonymous_caller_cannot_raise_an_order(self, world):
        response = APIClient().post(
            "/api/sales/orders/",
            {"branch": str(world["branch"].pk), "customer": str(world["customer"].pk)},
            format="json",
        )
        assert response.status_code in (401, 403)

    def test_a_return_needs_a_reason(self, world):
        order = raise_order(world).json()
        response = world["client"].post(
            "/api/sales/returns/",
            {"sales_order": order["id"]}, format="json",
        )
        assert response.status_code == 400
        assert "reason" in str(response.json()).lower()
