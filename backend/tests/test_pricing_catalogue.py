"""Price books, versions, branch inheritance and applied-price snapshots.

The properties here are the ones that make multi-branch pricing survivable:
branch pricing stays sparse, published prices stop changing, and every charged
line keeps its own record of what it was charged.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.pricing.catalogue import PriceCatalogue
from apps.pricing.models import (
    AppliedPriceSnapshot,
    PriceAssignment,
    PriceBook,
    PriceBookEntry,
    PriceBookVersion,
)
from apps.pricing.resolution import AmbiguousPricing, NoPriceFound, PricingContext
from apps.tenancy.models import Tenant

TODAY = date(2026, 7, 26)


def cash(value: str) -> Decimal:
    return Decimal(value)


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Pricing Tenant", slug="pricing-tenant")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-P", name="Pharmacy Group")
    eldoret = Location.all_objects.create(tenant=tenant, organization=org, code="ELD", name="Eldoret")
    mombasa = Location.all_objects.create(tenant=tenant, organization=org, code="MSA", name="Mombasa")

    dose_form = DoseForm.objects.create(code="CAP-P", name="Capsule")
    clinical = ClinicalMedicinalProduct.objects.create(
        tenant=tenant, code="CMP-P", canonical_name="Amoxicillin 500mg", dose_form=dose_form
    )
    manufactured = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant, code="MP-P", brand_name="Amoxil", clinical_product=clinical
    )
    package = PackageDefinition.objects.create(code="PK21", description="21 caps", unit_of_measure="cap")
    sku = CommercialSKU.objects.create(
        tenant=tenant, sku_code="SKU-AMOX", display_name="Amoxil 500mg 21s",
        manufactured_product=manufactured, package_definition=package,
    )
    return {
        "tenant": tenant, "eldoret": eldoret, "mombasa": mombasa, "sku": sku,
    }


def make_book(world, *, code, scope, price, status="ACTIVE", branch=None,
              effective_from=None, effective_to=None, priority=0, currency="KES",
              minimum_quantity=Decimal("1")):
    book = PriceBook.all_objects.create(
        tenant=world["tenant"], code=code, name=code, scope_type=scope,
        currency=currency, priority=priority,
    )
    version = PriceBookVersion.all_objects.create(
        tenant=world["tenant"], price_book=book, version_number=1, status=status,
        effective_from=effective_from or TODAY - timedelta(days=30),
        effective_to=effective_to,
    )
    PriceBookEntry.all_objects.create(
        tenant=world["tenant"], version=version, sku=world["sku"],
        unit_price=cash(price), minimum_quantity=minimum_quantity,
    )
    PriceAssignment.all_objects.create(
        tenant=world["tenant"], price_book=book, scope_type=scope, branch=branch,
    )
    return book, version


def ctx(world, *, branch=None, **overrides):
    base = {
        "tenant_id": str(world["tenant"].pk),
        "branch_id": str((branch or world["eldoret"]).pk),
        "sku_id": str(world["sku"].pk),
        "service_date": TODAY,
        "quantity": Decimal("1"),
        "currency": "KES",
    }
    base.update(overrides)
    return PricingContext(**base)


# ─── branch pricing stays sparse ─────────────────────────────────────────────


class TestInheritance:
    def test_a_branch_with_no_override_inherits_the_tenant_price(self, world):
        """The whole point of sparsity.

        Four hundred branches must not mean four hundred copies of every price.
        """
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        resolved = PriceCatalogue.price(context=ctx(world))
        assert resolved.unit_price == cash("600.00")
        assert resolved.source == "TENANT_PRICE"

    def test_a_branch_override_wins_where_one_exists(self, world):
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        make_book(
            world, code="ELD-RETAIL", scope=PriceBook.ScopeType.BRANCH,
            price="650.00", branch=world["eldoret"],
        )
        resolved = PriceCatalogue.price(context=ctx(world))
        assert resolved.unit_price == cash("650.00")
        assert resolved.source == "BRANCH_PRICE"

    def test_one_branch_override_does_not_reach_another_branch(self, world):
        """The failure this prevents is a price crossing branches.

        Mombasa must not be charged Eldoret's override.
        """
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        make_book(
            world, code="ELD-RETAIL", scope=PriceBook.ScopeType.BRANCH,
            price="650.00", branch=world["eldoret"],
        )
        resolved = PriceCatalogue.price(context=ctx(world, branch=world["mombasa"]))
        assert resolved.unit_price == cash("600.00")
        assert resolved.source == "TENANT_PRICE"

    def test_the_same_item_carries_different_lawful_prices_by_branch(self, world):
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        make_book(
            world, code="ELD-RETAIL", scope=PriceBook.ScopeType.BRANCH,
            price="650.00", branch=world["eldoret"],
        )
        make_book(
            world, code="MSA-RETAIL", scope=PriceBook.ScopeType.BRANCH,
            price="680.00", branch=world["mombasa"],
        )
        assert PriceCatalogue.price(context=ctx(world)).unit_price == cash("650.00")
        assert PriceCatalogue.price(
            context=ctx(world, branch=world["mombasa"])
        ).unit_price == cash("680.00")
        # One item master, three prices, no duplicated product.
        assert CommercialSKU.all_objects.filter(tenant=world["tenant"]).count() == 1


# ─── only approved prices reach a till ───────────────────────────────────────


class TestPublishedOnly:
    def test_a_draft_version_is_never_charged_from(self, world):
        """A till charging from a draft is charging a figure nobody approved."""
        make_book(
            world, code="DRAFT-BOOK", scope=PriceBook.ScopeType.TENANT,
            price="600.00", status="DRAFT",
        )
        with pytest.raises(NoPriceFound):
            PriceCatalogue.price(context=ctx(world))

    def test_a_cancelled_version_is_not_charged_from(self, world):
        make_book(
            world, code="CANCELLED-BOOK", scope=PriceBook.ScopeType.TENANT,
            price="600.00", status="CANCELLED",
        )
        with pytest.raises(NoPriceFound):
            PriceCatalogue.price(context=ctx(world))

    def test_a_scheduled_version_applies_from_its_date(self, world):
        make_book(
            world, code="FUTURE-BOOK", scope=PriceBook.ScopeType.TENANT, price="700.00",
            status="SCHEDULED", effective_from=TODAY + timedelta(days=7),
        )
        with pytest.raises(NoPriceFound):
            PriceCatalogue.price(context=ctx(world))
        later = PriceCatalogue.price(
            context=ctx(world, service_date=TODAY + timedelta(days=7))
        )
        assert later.unit_price == cash("700.00")


# ─── published prices stop changing ──────────────────────────────────────────


class TestImmutability:
    def test_a_published_version_cannot_be_redated(self, world):
        """Re-dating rewrites what every historical receipt claims to charge."""
        _, version = make_book(
            world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00"
        )
        version.effective_from = TODAY - timedelta(days=365)
        with pytest.raises(ValidationError, match="cannot be re-dated"):
            version.save()

    def test_a_published_version_cannot_be_renumbered(self, world):
        _, version = make_book(
            world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00"
        )
        version.version_number = 99
        with pytest.raises(ValidationError):
            version.save()

    def test_a_published_version_may_still_retire(self, world):
        # ACTIVE to SUPERSEDED is how a version stops applying. What may not
        # change is what it says, not whether it still says it.
        _, version = make_book(
            world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00"
        )
        version.status = PriceBookVersion.Status.SUPERSEDED
        version.save()
        assert version.status == "SUPERSEDED"

    def test_a_draft_version_is_freely_editable(self, world):
        _, version = make_book(
            world, code="DRAFT-BOOK", scope=PriceBook.ScopeType.TENANT,
            price="600.00", status="DRAFT",
        )
        version.effective_from = TODAY
        version.save()

    def test_an_entry_in_a_published_version_cannot_be_edited(self, world):
        _, version = make_book(
            world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00"
        )
        entry = PriceBookEntry.all_objects.get(version=version)
        entry.unit_price = cash("999.00")
        with pytest.raises(ValidationError, match="cannot be edited"):
            entry.save()


# ─── two books of one scope ──────────────────────────────────────────────────


class TestScopeCollisions:
    def test_two_branch_books_of_equal_priority_refuse(self, world):
        make_book(
            world, code="ELD-A", scope=PriceBook.ScopeType.BRANCH,
            price="650.00", branch=world["eldoret"],
        )
        make_book(
            world, code="ELD-B", scope=PriceBook.ScopeType.BRANCH,
            price="700.00", branch=world["eldoret"],
        )
        with pytest.raises(AmbiguousPricing):
            PriceCatalogue.price(context=ctx(world))

    def test_priority_separates_two_books_of_one_scope(self, world):
        make_book(
            world, code="ELD-A", scope=PriceBook.ScopeType.BRANCH,
            price="650.00", branch=world["eldoret"],
        )
        make_book(
            world, code="ELD-PREMIUM", scope=PriceBook.ScopeType.BRANCH,
            price="720.00", branch=world["eldoret"], priority=3,
        )
        resolved = PriceCatalogue.price(context=ctx(world))
        assert resolved.unit_price == cash("720.00")


# ─── quantity bands ──────────────────────────────────────────────────────────


class TestBands:
    def test_a_wholesale_band_applies_only_at_volume(self, world):
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        make_book(
            world, code="ELD-BULK", scope=PriceBook.ScopeType.BRANCH, price="450.00",
            branch=world["eldoret"], minimum_quantity=Decimal("100"),
        )
        assert PriceCatalogue.price(
            context=ctx(world, quantity=Decimal("1"))
        ).unit_price == cash("600.00")
        assert PriceCatalogue.price(
            context=ctx(world, quantity=Decimal("100"))
        ).unit_price == cash("450.00")


# ─── the charge is recorded ──────────────────────────────────────────────────


class TestAppliedPrice:
    def test_a_charged_line_keeps_its_own_price(self, world):
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        context = ctx(world, quantity=Decimal("3"))
        resolved = PriceCatalogue.price(context=context)

        snapshot = PriceCatalogue.record_applied_price(
            context=context, resolved=resolved, line_reference="SALE-LINE-1"
        )
        assert snapshot.unit_price == cash("600.00")
        assert snapshot.line_total == cash("1800.00")
        assert snapshot.source == "TENANT_PRICE"

    def test_the_snapshot_survives_a_later_price_rise(self, world):
        """A receipt reprinted after a rise must show what the customer paid."""
        _, version = make_book(
            world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00"
        )
        context = ctx(world)
        snapshot = PriceCatalogue.record_applied_price(
            context=context, resolved=PriceCatalogue.price(context=context),
            line_reference="SALE-LINE-2",
        )

        # The price rises: a new version supersedes the old one.
        version.status = PriceBookVersion.Status.SUPERSEDED
        version.effective_to = TODAY
        PriceBookVersion.all_objects.filter(pk=version.pk).update(
            status="SUPERSEDED", effective_to=TODAY - timedelta(days=1)
        )
        new_version = PriceBookVersion.all_objects.create(
            tenant=world["tenant"], price_book=version.price_book, version_number=2,
            status="ACTIVE", effective_from=TODAY,
        )
        PriceBookEntry.all_objects.create(
            tenant=world["tenant"], version=new_version, sku=world["sku"],
            unit_price=cash("750.00"),
        )

        snapshot.refresh_from_db()
        assert snapshot.unit_price == cash("600.00")
        # And the current price really has moved, so the test is not vacuous.
        assert PriceCatalogue.price(context=ctx(world)).unit_price == cash("750.00")

    def test_a_snapshot_cannot_be_modified(self, world):
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        context = ctx(world)
        snapshot = PriceCatalogue.record_applied_price(
            context=context, resolved=PriceCatalogue.price(context=context),
            line_reference="SALE-LINE-3",
        )
        snapshot.unit_price = cash("1.00")
        with pytest.raises(ValidationError, match="cannot be modified"):
            snapshot.save()

    def test_a_line_cannot_be_priced_twice(self, world):
        # Two prices on one line, and nobody could say which was paid.
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        context = ctx(world)
        resolved = PriceCatalogue.price(context=context)
        PriceCatalogue.record_applied_price(
            context=context, resolved=resolved, line_reference="SALE-LINE-4"
        )
        with pytest.raises(ValidationError, match="already carries an applied price"):
            PriceCatalogue.record_applied_price(
                context=context, resolved=resolved, line_reference="SALE-LINE-4"
            )

    def test_the_trace_is_kept_on_the_snapshot(self, world):
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        make_book(
            world, code="ELD-RETAIL", scope=PriceBook.ScopeType.BRANCH,
            price="650.00", branch=world["eldoret"],
        )
        context = ctx(world)
        snapshot = PriceCatalogue.record_applied_price(
            context=context, resolved=PriceCatalogue.price(context=context),
            line_reference="SALE-LINE-5",
        )
        sources = [item["source"] for item in snapshot.resolution_trace]
        assert sources[0] == "BRANCH_PRICE"
        assert "TENANT_PRICE" in sources


# ─── tenant isolation ────────────────────────────────────────────────────────


class TestIsolation:
    def test_a_price_cannot_reference_another_tenants_item(self, world, db):
        """Refused at the model layer, not merely filtered out of queries.

        A price entry pointing at another tenant's product is the shape of a
        cross-tenant leak, and rejecting it on write is stronger than hoping
        every read remembers to scope itself.
        """
        other = Tenant.objects.create(name="Other Pharmacy", slug="other-pharmacy")
        other_book = PriceBook.all_objects.create(
            tenant=other, code="OTHER-RETAIL", name="Other", scope_type=PriceBook.ScopeType.TENANT
        )
        other_version = PriceBookVersion.all_objects.create(
            tenant=other, price_book=other_book, version_number=1, status="ACTIVE",
            effective_from=TODAY - timedelta(days=30),
        )

        with pytest.raises(ValidationError, match="different tenant"):
            PriceBookEntry.all_objects.create(
                tenant=other, version=other_version, sku=world["sku"], unit_price=cash("1.00")
            )

    def test_a_tenant_resolves_only_its_own_price(self, world, db):
        other = Tenant.objects.create(name="Third Pharmacy", slug="third-pharmacy")
        other_book = PriceBook.all_objects.create(
            tenant=other, code="THIRD-RETAIL", name="Third", scope_type=PriceBook.ScopeType.TENANT
        )
        PriceAssignment.all_objects.create(
            tenant=other, price_book=other_book, scope_type=PriceBook.ScopeType.TENANT
        )

        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        resolved = PriceCatalogue.price(context=ctx(world))
        assert resolved.unit_price == cash("600.00")
        assert resolved.reference.startswith("TENANT-RETAIL")

    def test_a_snapshot_is_scoped_to_its_tenant(self, world):
        make_book(world, code="TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT, price="600.00")
        context = ctx(world)
        PriceCatalogue.record_applied_price(
            context=context, resolved=PriceCatalogue.price(context=context),
            line_reference="SALE-LINE-6",
        )
        assert AppliedPriceSnapshot.all_objects.filter(
            tenant=world["tenant"], line_reference="SALE-LINE-6"
        ).exists()
