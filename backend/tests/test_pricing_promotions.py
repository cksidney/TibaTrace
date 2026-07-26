"""Promotion stacking.

Promotions are the one pricing construct designed to be generous, which is why
they need the tightest arithmetic. The failures here are not subtle -- they end
with a basket at or near zero, reached by combinations that each looked
reasonable in isolation.

Do not relax the cap or the default stacking rule. Both exist for the case
nobody thought about.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.pricing.promotions import (
    BenefitType,
    Promotion,
    PromotionEngine,
    StackingRule,
    money,
)

TODAY = date(2026, 7, 26)


def cash(value: str) -> Decimal:
    return Decimal(value)


def promo(code, value, *, benefit=BenefitType.PERCENTAGE_DISCOUNT,
          stacking=StackingRule.EXCLUSIVE, **overrides) -> Promotion:
    base = {
        "code": code,
        "benefit_type": benefit,
        "value": cash(str(value)),
        "stacking": stacking,
    }
    base.update(overrides)
    return Promotion(**base)


def apply(promotions, price="1000.00", **overrides):
    base = {
        "base_price": cash(price),
        "promotions": promotions,
        "branch_id": "eldoret",
        "sku_id": "sku-1",
        "quantity": Decimal("1"),
        "on_date": TODAY,
    }
    base.update(overrides)
    return PromotionEngine.apply(**base)


# ─── nothing stacks by default ───────────────────────────────────────────────


class TestDefaultStacking:
    def test_the_default_is_exclusive(self):
        """The default is what applies when somebody forgets to think about it."""
        assert Promotion(code="X", benefit_type=BenefitType.PERCENTAGE_DISCOUNT,
                         value=cash("10")).stacking == StackingRule.EXCLUSIVE

    def test_two_exclusive_promotions_do_not_combine(self):
        outcome = apply([promo("A", 20), promo("B", 20)])
        # 20% off 1000, not 36% and certainly not 40%.
        assert outcome.final_price == cash("800.00")
        assert outcome.applied == ("A",)

    def test_the_higher_priority_exclusive_wins(self):
        outcome = apply([
            promo("LOW", 30, priority=200),
            promo("HIGH", 10, priority=1),
        ])
        assert outcome.applied == ("HIGH",)
        # Priority decides, not generosity. A promotion marked to run first
        # runs first even when another would have discounted more.
        assert outcome.final_price == cash("900.00")

    def test_an_excluded_promotion_says_why(self):
        outcome = apply([promo("A", 20, priority=1), promo("B", 20, priority=2)])
        reasons = {item["code"]: item["reason"] for item in outcome.rejected}
        assert "excluded by A" in reasons["B"]


# ─── stacking compounds, it does not sum ─────────────────────────────────────


class TestCompounding:
    def test_two_stackable_offers_compound(self):
        """Two 20% offers leave 64%, not 60%.

        Summing percentages is how a basket reaches zero with four offers that
        each looked reasonable.
        """
        outcome = apply([
            promo("A", 20, stacking=StackingRule.STACKABLE),
            promo("B", 20, stacking=StackingRule.STACKABLE),
        ])
        assert outcome.final_price == cash("640.00")
        assert outcome.total_discount == cash("360.00")

    def test_three_stackable_offers_still_compound(self):
        outcome = apply([
            promo("A", 20, stacking=StackingRule.STACKABLE),
            promo("B", 20, stacking=StackingRule.STACKABLE),
            promo("C", 20, stacking=StackingRule.STACKABLE),
        ])
        # 0.8^3 = 0.512. Summed, it would have been 40% -- and a fifth offer
        # would have made the basket free.
        assert outcome.final_price == cash("512.00")

    def test_summing_would_have_given_a_different_answer(self):
        outcome = apply([
            promo("A", 50, stacking=StackingRule.STACKABLE),
            promo("B", 50, stacking=StackingRule.STACKABLE),
        ])
        # Compounded: 250. Summed: free.
        assert outcome.final_price == cash("250.00")
        assert outcome.final_price > cash("0.00")


# ─── stack limits ────────────────────────────────────────────────────────────


class TestStackLimit:
    def test_a_limit_stops_further_promotions(self):
        outcome = apply([
            promo("A", 10, stacking=StackingRule.STACKABLE_WITH_LIMIT, stack_limit=2),
            promo("B", 10, stacking=StackingRule.STACKABLE),
            promo("C", 10, stacking=StackingRule.STACKABLE),
        ])
        assert len(outcome.applied) == 2
        assert any("stack limit" in item["reason"] for item in outcome.rejected)

    def test_the_tightest_limit_governs(self):
        # A promotion permitting two and one permitting five combine under two.
        outcome = apply([
            promo("A", 10, stacking=StackingRule.STACKABLE_WITH_LIMIT, stack_limit=5),
            promo("B", 10, stacking=StackingRule.STACKABLE_WITH_LIMIT, stack_limit=2),
            promo("C", 10, stacking=StackingRule.STACKABLE),
        ])
        assert len(outcome.applied) == 2


# ─── best price only ─────────────────────────────────────────────────────────


class TestBestPriceOnly:
    def test_the_best_single_offer_wins(self):
        outcome = apply([
            promo("SMALL", 10, stacking=StackingRule.BEST_PRICE_ONLY),
            promo("LARGE", 30, stacking=StackingRule.BEST_PRICE_ONLY),
        ])
        assert outcome.applied == ("LARGE",)
        assert outcome.final_price == cash("700.00")

    def test_they_compete_rather_than_combine(self):
        outcome = apply([
            promo("A", 30, stacking=StackingRule.BEST_PRICE_ONLY),
            promo("B", 30, stacking=StackingRule.BEST_PRICE_ONLY),
        ])
        # 30% off, not 51%.
        assert outcome.final_price == cash("700.00")
        assert len(outcome.applied) == 1


# ─── the cap is absolute ─────────────────────────────────────────────────────


class TestCap:
    def test_the_cap_bounds_the_total(self):
        """The last line of defence.

        It holds even when every individual promotion was configured correctly
        and only the combination was not.
        """
        outcome = apply(
            [
                promo("A", 40, stacking=StackingRule.STACKABLE),
                promo("B", 40, stacking=StackingRule.STACKABLE),
            ],
            maximum_discount_percentage=cash("50"),
        )
        assert outcome.total_discount == cash("500.00")
        assert outcome.final_price == cash("500.00")
        assert outcome.capped is True

    def test_a_basket_cannot_reach_zero_under_a_cap(self):
        outcome = apply(
            [promo(f"P{i}", 50, stacking=StackingRule.STACKABLE) for i in range(6)],
            maximum_discount_percentage=cash("60"),
        )
        assert outcome.final_price == cash("400.00")
        assert outcome.final_price > cash("0.00")

    def test_an_uncapped_stack_is_reported_as_capped_when_it_bites(self):
        outcome = apply(
            [promo("A", 10, stacking=StackingRule.STACKABLE)],
            maximum_discount_percentage=cash("50"),
        )
        assert outcome.capped is False


# ─── a promotion cannot make a line negative ─────────────────────────────────


class TestFloor:
    def test_an_absolute_discount_larger_than_the_line_is_bounded(self):
        outcome = apply(
            [promo("BIG", 5000, benefit=BenefitType.ABSOLUTE_DISCOUNT)], price="1000.00"
        )
        assert outcome.final_price == cash("0.00")
        assert outcome.final_price >= cash("0.00")

    def test_a_fixed_price_above_the_current_one_discounts_nothing(self):
        # Not a promotion. Charging more because an "offer" applied would be
        # the worst possible reading of the word.
        outcome = apply(
            [promo("HIGHER", 1500, benefit=BenefitType.FIXED_PRICE)], price="1000.00"
        )
        assert outcome.final_price == cash("1000.00")

    def test_a_fixed_price_below_the_current_one_applies(self):
        outcome = apply(
            [promo("FIXED", 750, benefit=BenefitType.FIXED_PRICE)], price="1000.00"
        )
        assert outcome.final_price == cash("750.00")


# ─── budgets and redemptions ─────────────────────────────────────────────────


class TestExhaustion:
    def test_an_exhausted_redemption_limit_stops_applying(self):
        """Checked before granting, never reconciled afterwards.

        Afterwards means the money is already gone.
        """
        outcome = apply([promo("A", 20, redemption_limit=100, redemptions_used=100)])
        assert outcome.final_price == cash("1000.00")
        assert any("exhausted" in item["reason"] for item in outcome.rejected)

    def test_an_exhausted_budget_stops_applying(self):
        outcome = apply([
            promo("A", 20, budget=cash("150.00"), budget_spent=cash("100.00"))
        ])
        # The 200 discount would take spend to 300, past the 150 budget.
        assert outcome.final_price == cash("1000.00")

    def test_a_budget_with_headroom_still_applies(self):
        outcome = apply([
            promo("A", 20, budget=cash("5000.00"), budget_spent=cash("100.00"))
        ])
        assert outcome.final_price == cash("800.00")

    def test_an_uncapped_promotion_is_a_deliberate_choice(self):
        # None means uncapped, and it is not the default for a reason.
        assert Promotion(
            code="X", benefit_type=BenefitType.PERCENTAGE_DISCOUNT, value=cash("10")
        ).redemption_limit is None


# ─── eligibility ─────────────────────────────────────────────────────────────


class TestEligibility:
    def test_a_branch_promotion_does_not_reach_another_branch(self):
        outcome = apply([promo("ELD", 20, branch_ids=("eldoret",))], branch_id="mombasa")
        assert outcome.final_price == cash("1000.00")

    def test_an_empty_scope_means_everywhere(self):
        outcome = apply([promo("ALL", 20)], branch_id="mombasa")
        assert outcome.final_price == cash("800.00")

    def test_an_expired_promotion_does_not_apply(self):
        outcome = apply([promo("OLD", 20, valid_to=TODAY - timedelta(days=1))])
        assert outcome.final_price == cash("1000.00")

    def test_a_future_promotion_does_not_apply_early(self):
        outcome = apply([promo("SOON", 20, valid_from=TODAY + timedelta(days=1))])
        assert outcome.final_price == cash("1000.00")

    def test_a_quantity_threshold_is_respected(self):
        offer = promo("BULK", 20, minimum_quantity=Decimal("10"))
        assert apply([offer], quantity=Decimal("1")).final_price == cash("1000.00")
        assert apply([offer], quantity=Decimal("10")).final_price == cash("800.00")

    def test_a_segment_promotion_does_not_reach_other_customers(self):
        offer = promo("STAFF", 20, customer_segments=("STAFF",))
        assert apply([offer], customer_segment=None).final_price == cash("1000.00")
        assert apply([offer], customer_segment="STAFF").final_price == cash("800.00")


class TestReporting:
    def test_the_outcome_reports_what_applied(self):
        outcome = apply([
            promo("A", 10, stacking=StackingRule.STACKABLE),
            promo("B", 10, stacking=StackingRule.STACKABLE),
        ])
        assert set(outcome.applied) == {"A", "B"}

    def test_the_effective_percentage_is_reported(self):
        outcome = apply([
            promo("A", 20, stacking=StackingRule.STACKABLE),
            promo("B", 20, stacking=StackingRule.STACKABLE),
        ])
        # 36%, which is the number a manager asking "how much did we give away"
        # actually wants -- not the 40% the two offers advertise.
        assert outcome.discount_percentage == cash("36.00")


class TestArithmetic:
    def test_money_never_goes_through_float(self):
        assert money(0.1) == cash("0.10")

    @pytest.mark.parametrize("value,expected", [("10.005", "10.01"), ("10.004", "10.00")])
    def test_rounding_is_half_up(self, value, expected):
        assert money(value) == cash(expected)
