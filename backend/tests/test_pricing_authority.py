"""Which table prices what, pinned.

There are two price tables and they are not interchangeable. `PriceListEntry`
bills business-to-business quotations and sales orders; `PriceBookEntry` backs
the versioned pricing engine and its resolution endpoint. Nothing in the code
says so, and the two are indistinguishable by name, so the next person to add a
price will guess.

These tests make the boundary executable: change which table a channel reads
from and one of them fails, rather than the mistake surfacing as a wrong number
on an invoice.

See docs/PRICING_AUTHORITY_DECISION.md.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.customers.models import Customer
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.sales.models import PriceList, PriceListEntry
from apps.tenancy.models import Tenant


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Price Tenant", slug="price-tenant")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-P", name="Org")
    Location.all_objects.create(
        tenant=tenant, organization=org, code="BR-P", name="Branch"
    )
    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    pack = PackageDefinition.objects.get_or_create(
        code="PK-P", defaults={"description": "Pack", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code="CMP-P", canonical_name="Atenolol 50mg", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code="MP-P", brand_name="Tenormin", clinical_product=clinical
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-P", display_name="Tenormin 50mg",
        manufactured_product=manufactured, package_definition=pack,
    )
    customer = Customer.all_objects.create(
        tenant=tenant, customer_number="CUS-P", legal_name="Wholesale Buyer",
        customer_type="WHOLESALE",
    )
    now = timezone.now()
    price_list = PriceList.all_objects.create(
        tenant=tenant, code="PL-DEFAULT", name="Default",
        is_default=True, status=PriceList.Status.ACTIVE,
        effective_from=now - timedelta(days=10),
    )
    return {
        "tenant": tenant, "sku": sku, "customer": customer,
        "price_list": price_list, "now": now,
    }


def add_entry(world, *, unit_price, minimum_quantity=1):
    return PriceListEntry.all_objects.create(
        tenant=world["tenant"], price_list=world["price_list"], sku=world["sku"],
        unit_price=Decimal(unit_price), minimum_quantity=minimum_quantity,
        is_active=True,
        # Distinct dates: (price_list, sku, effective_from) is unique, so two
        # quantity breaks for one SKU cannot share a start date.
        effective_from=world["now"] - timedelta(days=5 + int(minimum_quantity)),
    )


def price_line(world, quantity=1):
    from apps.sales.services import CommercialPricingService

    return CommercialPricingService.resolve_price(
        tenant=world["tenant"], customer=world["customer"],
        sku=world["sku"], quantity=quantity,
    )


class TestBusinessToBusinessPricesFromThePriceList:
    """The live path. If this breaks, quotations and orders bill the wrong
    figure, which is discovered on an invoice rather than in a test."""

    def test_a_line_takes_its_price_from_the_price_list_entry(self, world):
        add_entry(world, unit_price="240.00")
        result = price_line(world, quantity=1)
        assert Decimal(str(result["base_unit_price"])) == Decimal("240.00")

    def test_a_quantity_break_is_honoured(self, world):
        # Two entries, and the larger break wins once the quantity reaches it.
        add_entry(world, unit_price="240.00", minimum_quantity=1)
        add_entry(world, unit_price="200.00", minimum_quantity=50)
        assert Decimal(str(price_line(world, 10)["base_unit_price"])) == Decimal("240.00")
        assert Decimal(str(price_line(world, 60)["base_unit_price"])) == Decimal("200.00")

    def test_an_expired_entry_is_not_used(self, world):
        entry = add_entry(world, unit_price="240.00")
        entry.effective_to = world["now"] - timedelta(days=1)
        entry.save(update_fields=["effective_to"])
        # Falls back rather than billing a price that has lapsed.
        assert Decimal(str(price_line(world)["base_unit_price"])) != Decimal("240.00")


class TestTheTwoTablesAreSeparate:
    def test_a_price_book_entry_does_not_price_a_sales_line(self, world):
        """The boundary.

        A price book covering this SKU must not change what a sales order bills,
        because sales prices from the price list. If someone wires the pricing
        engine into apps/sales without migrating the data, this fails -- which is
        the point.
        """
        add_entry(world, unit_price="240.00")
        before = Decimal(str(price_line(world)["base_unit_price"]))

        from apps.pricing.models import PriceBook, PriceBookEntry, PriceBookVersion

        book = PriceBook.all_objects.create(
            tenant=world["tenant"], code="PB-1", name="Retail",
            scope_type=PriceBook.ScopeType.TENANT,
        )
        version = PriceBookVersion.all_objects.create(
            tenant=world["tenant"], price_book=book, version_number=1,
            status=PriceBookVersion.Status.ACTIVE,
            effective_from=world["now"].date() - timedelta(days=1),
        )
        PriceBookEntry.all_objects.create(
            tenant=world["tenant"], version=version, sku=world["sku"],
            unit_price=Decimal("999.00"),
        )

        after = Decimal(str(price_line(world)["base_unit_price"]))
        assert after == before == Decimal("240.00"), (
            "A price book entry changed what a sales order bills. The two tables "
            "serve different channels; see docs/PRICING_AUTHORITY_DECISION.md."
        )
