"""Deterministic price resolution.

The failures these guard against all end the same way: a customer charged an
amount nobody can explain, or stock sold for nothing.

Do not relax the ambiguity or the no-price refusals into defaults. Both are
configuration errors, and both are cheaper to fix at the till than to discover
in a month's takings.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.pricing.resolution import (
    AmbiguousPricing,
    NoPriceFound,
    PriceCandidate,
    PriceResolutionService,
    PriceSource,
    PricingContext,
    PricingError,
    money,
    ranks_are_unique,
)

TODAY = date(2026, 7, 26)


def cash(value: str) -> Decimal:
    return Decimal(value)


def context(**overrides) -> PricingContext:
    base = {
        "tenant_id": "t1",
        "branch_id": "eldoret",
        "sku_id": "sku-amox-500",
        "service_date": TODAY,
        "quantity": Decimal("1"),
        "currency": "KES",
    }
    base.update(overrides)
    return PricingContext(**base)


def candidate(source_tuple, price: str, **overrides) -> PriceCandidate:
    source, rank = source_tuple
    base = {
        "source": source,
        "rank": rank,
        "unit_price": cash(price),
        "reference": f"{source}-ref",
        "currency": "KES",
    }
    base.update(overrides)
    return PriceCandidate(**base)


# ─── precedence is total ─────────────────────────────────────────────────────


class TestPrecedence:
    def test_every_source_has_a_distinct_rank(self):
        """Two sources sharing a rank makes every resolution between them
        ambiguous -- a runtime failure for every tenant at once."""
        assert ranks_are_unique()

    def test_a_manual_override_beats_everything(self):
        candidates = [
            candidate(PriceSource.TENANT_PRICE, "600.00"),
            candidate(PriceSource.BRANCH_PRICE, "650.00"),
            candidate(PriceSource.MANUAL_OVERRIDE, "500.00"),
        ]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert resolved.source == "MANUAL_OVERRIDE"
        assert resolved.unit_price == cash("500.00")

    def test_an_insurer_tariff_beats_retail(self):
        # An insured line is priced by the contract, not the shelf.
        candidates = [
            candidate(PriceSource.BRANCH_PRICE, "1000.00"),
            candidate(PriceSource.INSURANCE_TARIFF, "850.00"),
        ]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert resolved.source == "INSURANCE_TARIFF"

    def test_a_customer_contract_beats_tenant_retail(self):
        candidates = [
            candidate(PriceSource.TENANT_PRICE, "600.00"),
            candidate(PriceSource.CUSTOMER_CONTRACT, "540.00"),
        ]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert resolved.source == "CUSTOMER_CONTRACT"

    def test_a_branch_price_beats_the_tenant_price(self):
        candidates = [
            candidate(PriceSource.TENANT_PRICE, "600.00"),
            candidate(PriceSource.BRANCH_PRICE, "650.00"),
        ]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert resolved.source == "BRANCH_PRICE"
        # More specific wins even when it is dearer. Precedence is about
        # authority, not about finding the lowest number.
        assert resolved.unit_price == cash("650.00")

    def test_a_branch_promotion_beats_the_branch_price(self):
        candidates = [
            candidate(PriceSource.BRANCH_PRICE, "650.00"),
            candidate(PriceSource.BRANCH_PROMOTION, "550.00"),
        ]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert resolved.source == "BRANCH_PROMOTION"

    def test_the_tenant_price_is_the_fallback_when_no_branch_price_exists(self):
        """Branch pricing is sparse by design.

        A branch with no override inherits, so a tenant with four hundred
        branches does not carry four hundred copies of every price.
        """
        candidates = [candidate(PriceSource.TENANT_PRICE, "600.00")]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert resolved.source == "TENANT_PRICE"
        assert resolved.unit_price == cash("600.00")

    def test_the_full_ladder_resolves_to_the_top(self):
        candidates = [
            candidate(PriceSource.BASE_FALLBACK, "500.00"),
            candidate(PriceSource.TENANT_PRICE, "600.00"),
            candidate(PriceSource.TENANT_PROMOTION, "580.00"),
            candidate(PriceSource.BRANCH_GROUP_PRICE, "620.00"),
            candidate(PriceSource.BRANCH_PRICE, "650.00"),
            candidate(PriceSource.BRANCH_PROMOTION, "610.00"),
            candidate(PriceSource.CUSTOMER_SEGMENT, "590.00"),
            candidate(PriceSource.CUSTOMER_CONTRACT, "540.00"),
            candidate(PriceSource.INSURANCE_TARIFF, "850.00"),
            candidate(PriceSource.MANUAL_OVERRIDE, "500.00"),
        ]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert resolved.source == "MANUAL_OVERRIDE"
        assert len(resolved.considered) == 10


# ─── ambiguity fails closed ──────────────────────────────────────────────────


class TestAmbiguity:
    def test_two_sources_of_equal_precedence_refuse(self):
        """Two active branch overrides for one item is a configuration error.

        Choosing between them makes the price depend on row order, and nobody
        would be able to reproduce the charge afterwards.
        """
        candidates = [
            candidate(PriceSource.BRANCH_PRICE, "650.00", reference="override-a"),
            candidate(PriceSource.BRANCH_PRICE, "700.00", reference="override-b"),
        ]
        with pytest.raises(AmbiguousPricing) as refused:
            PriceResolutionService.resolve(candidates=candidates, context=context())
        # The message names both, so the person fixing it knows which two.
        assert "override-a" in str(refused.value)
        assert "override-b" in str(refused.value)

    def test_ambiguity_is_not_resolved_by_taking_the_lower_price(self):
        candidates = [
            candidate(PriceSource.BRANCH_PRICE, "650.00"),
            candidate(PriceSource.BRANCH_PRICE, "600.00"),
        ]
        with pytest.raises(AmbiguousPricing):
            PriceResolutionService.resolve(candidates=candidates, context=context())

    def test_a_clear_winner_above_a_tie_still_resolves(self):
        # The tie is below the winner, so it never decides anything.
        candidates = [
            candidate(PriceSource.MANUAL_OVERRIDE, "500.00"),
            candidate(PriceSource.TENANT_PRICE, "600.00"),
            candidate(PriceSource.TENANT_PRICE, "610.00"),
        ]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert resolved.source == "MANUAL_OVERRIDE"


# ─── no price is not a free item ─────────────────────────────────────────────


class TestNoPrice:
    def test_no_candidates_refuses(self):
        with pytest.raises(NoPriceFound):
            PriceResolutionService.resolve(candidates=[], context=context())

    def test_nothing_applicable_refuses_rather_than_returning_zero(self):
        """Defaulting to zero has sold stock for nothing more than once."""
        expired = candidate(
            PriceSource.TENANT_PRICE, "600.00",
            effective_from=TODAY - timedelta(days=90),
            effective_to=TODAY - timedelta(days=1),
        )
        with pytest.raises(NoPriceFound):
            PriceResolutionService.resolve(candidates=[expired], context=context())


# ─── effective dating ────────────────────────────────────────────────────────


class TestEffectiveDating:
    def test_a_future_price_is_not_used_early(self):
        future = candidate(
            PriceSource.BRANCH_PRICE, "700.00", effective_from=TODAY + timedelta(days=7)
        )
        current = candidate(PriceSource.TENANT_PRICE, "600.00")
        resolved = PriceResolutionService.resolve(
            candidates=[future, current], context=context()
        )
        assert resolved.source == "TENANT_PRICE"

    def test_a_future_price_applies_on_its_date(self):
        future = candidate(
            PriceSource.BRANCH_PRICE, "700.00", effective_from=TODAY + timedelta(days=7)
        )
        current = candidate(PriceSource.TENANT_PRICE, "600.00")
        resolved = PriceResolutionService.resolve(
            candidates=[future, current],
            context=context(service_date=TODAY + timedelta(days=7)),
        )
        assert resolved.source == "BRANCH_PRICE"

    def test_an_expired_price_is_ignored(self):
        expired = candidate(
            PriceSource.BRANCH_PRICE, "700.00", effective_to=TODAY - timedelta(days=1)
        )
        current = candidate(PriceSource.TENANT_PRICE, "600.00")
        resolved = PriceResolutionService.resolve(
            candidates=[expired, current], context=context()
        )
        assert resolved.source == "TENANT_PRICE"

    def test_a_backdated_sale_uses_the_price_of_its_service_date(self):
        """Historical transactions must not be repriced by today's rates."""
        old = candidate(
            PriceSource.TENANT_PRICE, "500.00",
            effective_from=TODAY - timedelta(days=90),
            effective_to=TODAY - timedelta(days=30),
        )
        current = candidate(
            PriceSource.TENANT_PRICE, "600.00", effective_from=TODAY - timedelta(days=29)
        )
        resolved = PriceResolutionService.resolve(
            candidates=[old, current], context=context(service_date=TODAY - timedelta(days=60))
        )
        assert resolved.unit_price == cash("500.00")


# ─── quantity bands and currency ─────────────────────────────────────────────


class TestBands:
    def test_a_wholesale_band_does_not_apply_below_its_minimum(self):
        wholesale = candidate(
            PriceSource.BRANCH_PRICE, "450.00", minimum_quantity=Decimal("100")
        )
        retail = candidate(PriceSource.TENANT_PRICE, "600.00")
        resolved = PriceResolutionService.resolve(
            candidates=[wholesale, retail], context=context(quantity=Decimal("10"))
        )
        assert resolved.unit_price == cash("600.00")

    def test_the_band_applies_at_its_minimum(self):
        wholesale = candidate(
            PriceSource.BRANCH_PRICE, "450.00", minimum_quantity=Decimal("100")
        )
        retail = candidate(PriceSource.TENANT_PRICE, "600.00")
        resolved = PriceResolutionService.resolve(
            candidates=[wholesale, retail], context=context(quantity=Decimal("100"))
        )
        assert resolved.unit_price == cash("450.00")

    def test_a_price_in_another_currency_is_not_converted(self):
        """Silently resolving a dollar price against a shilling till is worse
        than finding no price at all."""
        foreign = candidate(PriceSource.BRANCH_PRICE, "5.00", currency="USD")
        with pytest.raises(NoPriceFound):
            PriceResolutionService.resolve(candidates=[foreign], context=context())


# ─── the context is required ─────────────────────────────────────────────────


class TestContextRequirements:
    def test_a_branch_is_required(self):
        # Resolving from an item alone is how one branch's price ends up on
        # another branch's receipt.
        with pytest.raises(PricingError, match="branch"):
            PricingContext(
                tenant_id="t1", branch_id="", sku_id="sku-1", service_date=TODAY
            )

    def test_a_tenant_is_required(self):
        with pytest.raises(PricingError, match="tenant"):
            PricingContext(
                tenant_id="", branch_id="eldoret", sku_id="sku-1", service_date=TODAY
            )

    def test_a_service_date_is_required(self):
        with pytest.raises(PricingError, match="service date"):
            PricingContext(
                tenant_id="t1", branch_id="eldoret", sku_id="sku-1", service_date=None
            )

    def test_the_same_context_hashes_identically(self):
        assert context().digest() == context().digest()

    def test_a_different_branch_hashes_differently(self):
        assert context().digest() != context(branch_id="mombasa").digest()

    def test_a_different_date_hashes_differently(self):
        assert context().digest() != context(service_date=TODAY - timedelta(days=1)).digest()


# ─── the answer explains itself ──────────────────────────────────────────────


class TestExplanation:
    def test_the_winner_is_first_in_the_trace(self):
        candidates = [
            candidate(PriceSource.TENANT_PRICE, "600.00"),
            candidate(PriceSource.BRANCH_PRICE, "650.00"),
        ]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert resolved.considered[0]["source"] == "BRANCH_PRICE"

    def test_rejected_alternatives_are_retained(self):
        """"Why is this 650 here and 600 there" must be answerable.

        Without it the usual outcome is somebody overriding the price by hand
        and moving on, which loses the reason permanently.
        """
        candidates = [
            candidate(PriceSource.TENANT_PRICE, "600.00"),
            candidate(PriceSource.BRANCH_PRICE, "650.00"),
        ]
        resolved = PriceResolutionService.resolve(candidates=candidates, context=context())
        assert len(resolved.rejected) == 1
        assert resolved.rejected[0]["source"] == "TENANT_PRICE"
        assert "TENANT_PRICE" in resolved.explain()

    def test_a_sole_source_says_so(self):
        resolved = PriceResolutionService.resolve(
            candidates=[candidate(PriceSource.TENANT_PRICE, "600.00")], context=context()
        )
        assert "no other source applied" in resolved.explain()

    def test_the_context_hash_is_carried_on_the_answer(self):
        resolved = PriceResolutionService.resolve(
            candidates=[candidate(PriceSource.TENANT_PRICE, "600.00")], context=context()
        )
        assert resolved.context_hash == context().digest()


# ─── arithmetic ──────────────────────────────────────────────────────────────


class TestArithmetic:
    def test_money_never_goes_through_float(self):
        assert money(0.1) == cash("0.10")

    def test_rounding_is_half_up(self):
        assert money("10.005") == cash("10.01")

    def test_a_line_total_rounds_once_at_the_end(self):
        """Rounding the unit price then multiplying compounds the error.

        A hundred-unit line ends up a shilling out from the same line priced by
        hand, and nobody can see why.
        """
        total = PriceResolutionService.line_total(
            unit_price=Decimal("33.333"), quantity=Decimal("100")
        )
        assert total == cash("3333.30")

    def test_repeated_addition_does_not_drift(self):
        total = Decimal("0.00")
        for _ in range(10):
            total += money("0.10")
        assert total == cash("1.00")
