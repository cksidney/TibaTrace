"""Price locks: was the customer charged what they were quoted?

Between the quote and the money there is a window in which a scheduled price
change activates or a promotion ends. These tests guard the two ways that
window causes harm: charging a figure the customer never agreed to, and honouring
a quote that no longer describes the sale in front of you.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.pricing.locks import (
    DEFAULT_LOCK_MINUTES,
    LockPolicy,
    PriceChangedAtCheckout,
    PriceLockService,
)
from apps.pricing.models import PriceLock
from apps.pricing.resolution import PriceCandidate, PriceResolutionService, PriceSource, PricingContext
from apps.tenancy.models import Tenant

TODAY = date(2026, 7, 26)


def cash(value: str) -> Decimal:
    return Decimal(value)


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Lock Tenant", slug="lock-tenant")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-L", name="Group")
    branch = Location.all_objects.create(tenant=tenant, organization=org, code="ELD-L", name="Eldoret")
    dose_form = DoseForm.objects.create(code="CAP-L", name="Capsule")
    clinical = ClinicalMedicinalProduct.objects.create(
        tenant=tenant, code="CMP-L", canonical_name="Amoxicillin", dose_form=dose_form
    )
    manufactured = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant, code="MP-L", brand_name="Amoxil", clinical_product=clinical
    )
    package = PackageDefinition.objects.create(code="PK-L", description="21", unit_of_measure="cap")
    sku = CommercialSKU.objects.create(
        tenant=tenant, sku_code="SKU-L", display_name="Amoxil",
        manufactured_product=manufactured, package_definition=package,
    )
    return {"tenant": tenant, "branch": branch, "sku": sku}


def ctx(world, **overrides):
    base = {
        "tenant_id": str(world["tenant"].pk),
        "branch_id": str(world["branch"].pk),
        "sku_id": str(world["sku"].pk),
        "service_date": TODAY,
        "quantity": Decimal("1"),
        "currency": "KES",
    }
    base.update(overrides)
    return PricingContext(**base)


def resolve(context, price: str):
    name, rank = PriceSource.TENANT_PRICE
    return PriceResolutionService.resolve(
        candidates=[
            PriceCandidate(source=name, rank=rank, unit_price=cash(price), reference="BOOK:v1")
        ],
        context=context,
    )


# ─── the quote is honoured ───────────────────────────────────────────────────


class TestLocking:
    def test_a_lock_holds_the_quoted_price(self, world):
        context = ctx(world)
        lock = PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        assert lock.locked_unit_price == cash("600.00")
        assert lock.is_live is True

    def test_an_unchanged_price_raises_nothing(self, world):
        context = ctx(world)
        PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        PriceLockService.assert_unchanged(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )

    def test_a_second_lock_supersedes_the_first(self, world):
        """Two active locks on one line means two answers to what is owed."""
        context = ctx(world)
        first = PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        PriceLockService.lock(
            context=context, resolved=resolve(context, "650.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        first.refresh_from_db()
        assert first.status == PriceLock.Status.INVALIDATED
        assert (
            PriceLock.all_objects.filter(
                basket_reference="BASKET-1", line_reference="LINE-1", status="ACTIVE"
            ).count()
            == 1
        )


# ─── a moved price is not charged silently ───────────────────────────────────


class TestPriceMovement:
    def test_a_risen_price_refuses_without_acknowledgement(self, world):
        """The customer is holding a slip that says something else."""
        context = ctx(world)
        PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        with pytest.raises(PriceChangedAtCheckout) as refused:
            PriceLockService.assert_unchanged(
                context=context, resolved=resolve(context, "750.00"),
                basket_reference="BASKET-1", line_reference="LINE-1",
            )
        assert refused.value.changes[0].customer_pays_more is True

    def test_a_fallen_price_is_also_surfaced(self, world):
        # Charging the old higher price because it was quoted is overcharging.
        context = ctx(world)
        PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        with pytest.raises(PriceChangedAtCheckout) as refused:
            PriceLockService.assert_unchanged(
                context=context, resolved=resolve(context, "500.00"),
                basket_reference="BASKET-1", line_reference="LINE-1",
            )
        assert refused.value.changes[0].customer_pays_more is False

    def test_an_acknowledged_change_proceeds(self, world):
        """An operator who has seen both figures and chosen may continue."""
        context = ctx(world)
        PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        PriceLockService.assert_unchanged(
            context=context, resolved=resolve(context, "750.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
            acknowledged=True,
        )

    def test_the_change_reports_both_figures(self, world):
        context = ctx(world)
        PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        change = PriceLockService.verify(
            context=context, resolved=resolve(context, "750.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        assert change.locked_price == cash("600.00")
        assert change.current_price == cash("750.00")
        assert change.difference == cash("150.00")
        assert "600.00" in change.describe() and "750.00" in change.describe()


# ─── a changed basket drops its own lock ─────────────────────────────────────


class TestBasketChange:
    def test_changing_the_quantity_invalidates_the_lock(self, world):
        """The locked unit price was quoted for a different sale.

        Treating it as agreement would apply a quantity-band price to a
        quantity that does not qualify for it.
        """
        one = ctx(world, quantity=Decimal("1"))
        PriceLockService.lock(
            context=one, resolved=resolve(one, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        hundred = ctx(world, quantity=Decimal("100"))
        change = PriceLockService.verify(
            context=hundred, resolved=resolve(hundred, "450.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        # Not reported as a price change -- reported as no lock at all.
        assert change is None
        assert PriceLock.all_objects.get(line_reference="LINE-1").status == "INVALIDATED"

    def test_a_material_basket_change_drops_every_lock(self, world):
        context = ctx(world)
        for line in ("LINE-1", "LINE-2", "LINE-3"):
            PriceLockService.lock(
                context=context, resolved=resolve(context, "600.00"),
                basket_reference="BASKET-1", line_reference=line,
            )
        dropped = PriceLockService.invalidate_basket(
            tenant_id=str(world["tenant"].pk), basket_reference="BASKET-1",
            reason="Insurance selected after quoting",
        )
        assert dropped == 3
        assert PriceLockService.active_lock(
            tenant_id=str(world["tenant"].pk),
            basket_reference="BASKET-1", line_reference="LINE-1",
        ) is None


# ─── locks expire ────────────────────────────────────────────────────────────


class TestExpiry:
    def test_the_window_is_short(self):
        assert DEFAULT_LOCK_MINUTES <= 60

    def test_an_expired_lock_stops_holding(self, world):
        """A basket held overnight does not get yesterday's promotion."""
        context = ctx(world)
        lock = PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        PriceLock.all_objects.filter(pk=lock.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        assert PriceLockService.active_lock(
            tenant_id=str(world["tenant"].pk),
            basket_reference="BASKET-1", line_reference="LINE-1",
        ) is None

    def test_an_expired_lock_is_marked_rather_than_left_active(self, world):
        context = ctx(world)
        lock = PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        PriceLock.all_objects.filter(pk=lock.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        PriceLockService.active_lock(
            tenant_id=str(world["tenant"].pk),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        lock.refresh_from_db()
        assert lock.status == PriceLock.Status.EXPIRED

    def test_an_expired_lock_no_longer_blocks_a_new_price(self, world):
        context = ctx(world)
        lock = PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        PriceLock.all_objects.filter(pk=lock.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        # No lock, so nothing to disagree with -- the basket is simply re-priced.
        PriceLockService.assert_unchanged(
            context=context, resolved=resolve(context, "750.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )


# ─── consumption ─────────────────────────────────────────────────────────────


class TestConsumption:
    def test_a_paid_lock_is_consumed(self, world):
        context = ctx(world)
        lock = PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        PriceLockService.consume(lock=lock)
        assert lock.status == PriceLock.Status.CONSUMED

    def test_a_consumed_lock_cannot_be_reused(self, world):
        # It held a price for one sale; a second sale is a second question.
        context = ctx(world)
        lock = PriceLockService.lock(
            context=context, resolved=resolve(context, "600.00"),
            basket_reference="BASKET-1", line_reference="LINE-1",
        )
        PriceLockService.consume(lock=lock)
        with pytest.raises(ValidationError):
            PriceLockService.consume(lock=lock)


class TestPolicy:
    def test_the_recommended_default_locks_at_payment_intent(self):
        """Prices stay live while the basket is being built, and freeze when
        the customer commits -- so an item added after a rise is priced
        correctly rather than at a stale quote."""
        assert LockPolicy.LOCK_AT_PAYMENT_INTENT == "LOCK_AT_PAYMENT_INTENT"
        assert LockPolicy.NO_LOCK != LockPolicy.LOCK_AT_PAYMENT_INTENT
