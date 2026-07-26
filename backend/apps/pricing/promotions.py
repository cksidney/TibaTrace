"""Promotions, and the rules that stop them compounding into a free basket.

Promotions are the one pricing construct designed to be generous, which is
exactly why they need the tightest arithmetic. Three 20% offers applied to one
line is 48.8% off if they compound, or 60% off if somebody sums the percentages
and applies once. Neither is what anybody signed off, and both are reached by
writing the obvious loop.

Four rules.

**Stacking is declared, not assumed.** Every promotion says whether it may
combine. An EXCLUSIVE promotion runs alone. BEST_PRICE_ONLY competes and the
cheapest single offer wins. Nothing stacks by default, because the default is
what applies when somebody forgets to think about it.

**A cap bounds the total.** However many promotions apply, the combined discount
cannot exceed the basket's configured maximum. The cap is the last line of
defence and it is absolute -- it holds even when every individual promotion was
correctly configured.

**Discounts compound, they do not sum.** Two 20% offers leave 64% of the price,
not 60%. Summing percentages is how a basket reaches zero with four offers that
each looked reasonable.

**A promotion that has run out stops applying.** Redemption caps and budgets are
checked before a discount is granted, not reconciled afterwards -- afterwards
means the money is already gone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
PENNY = Decimal("0.01")
HUNDRED = Decimal("100")


def money(value) -> Decimal:
    if value is None:
        return ZERO
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


class StackingRule:
    """How a promotion behaves alongside others."""

    #: Runs alone. If it wins, nothing else applies to the line.
    EXCLUSIVE = "EXCLUSIVE"
    #: May combine freely with other stackable promotions, subject to the cap.
    STACKABLE = "STACKABLE"
    #: May combine, but only up to a stated number of promotions.
    STACKABLE_WITH_LIMIT = "STACKABLE_WITH_LIMIT"
    #: Competes rather than combines: the single best offer wins.
    BEST_PRICE_ONLY = "BEST_PRICE_ONLY"


class BenefitType:
    PERCENTAGE_DISCOUNT = "PERCENTAGE_DISCOUNT"
    ABSOLUTE_DISCOUNT = "ABSOLUTE_DISCOUNT"
    FIXED_PRICE = "FIXED_PRICE"


@dataclass(frozen=True)
class Promotion:
    """One offer, with everything needed to decide whether it applies."""

    code: str
    benefit_type: str
    #: Percentage, cash amount, or the fixed price, depending on benefit_type.
    value: Decimal
    #: Lower number applies first and wins an exclusivity contest.
    priority: int = 100
    stacking: str = StackingRule.EXCLUSIVE
    stack_limit: int = 1

    valid_from: date | None = None
    valid_to: date | None = None
    branch_ids: tuple[str, ...] = ()
    sku_ids: tuple[str, ...] = ()
    customer_segments: tuple[str, ...] = ()
    minimum_quantity: Decimal = Decimal("1")

    #: How many times it may be redeemed in total, and how much it may cost.
    #: None means uncapped, which is a deliberate choice somebody has to make.
    redemption_limit: int | None = None
    redemptions_used: int = 0
    budget: Decimal | None = None
    budget_spent: Decimal = ZERO

    def is_live(self, on_date: date) -> bool:
        if self.valid_from and on_date < self.valid_from:
            return False
        if self.valid_to and on_date > self.valid_to:
            return False
        return True

    def has_headroom(self, *, amount: Decimal) -> bool:
        """Whether the offer can still afford this discount.

        Checked before granting, never reconciled afterwards -- afterwards
        means the money is already gone.
        """
        if self.redemption_limit is not None and self.redemptions_used >= self.redemption_limit:
            return False
        if self.budget is not None and money(self.budget_spent) + money(amount) > money(self.budget):
            return False
        return True

    def applies_to(self, *, branch_id: str, sku_id: str, quantity: Decimal,
                   customer_segment: str | None, on_date: date) -> bool:
        if not self.is_live(on_date):
            return False
        # An empty scope means "everywhere", a populated one means "only here".
        if self.branch_ids and str(branch_id) not in self.branch_ids:
            return False
        if self.sku_ids and str(sku_id) not in self.sku_ids:
            return False
        if self.customer_segments and (customer_segment or "") not in self.customer_segments:
            return False
        return Decimal(str(quantity)) >= Decimal(str(self.minimum_quantity))

    def discount_on(self, price: Decimal) -> Decimal:
        """What this offer takes off the given price.

        Never more than the price itself. A fixed price above the current one
        is not a promotion, and an absolute discount larger than the line would
        otherwise produce a negative charge.
        """
        price = money(price)
        if self.benefit_type == BenefitType.PERCENTAGE_DISCOUNT:
            raw = price * (money(self.value) / HUNDRED)
        elif self.benefit_type == BenefitType.ABSOLUTE_DISCOUNT:
            raw = money(self.value)
        elif self.benefit_type == BenefitType.FIXED_PRICE:
            raw = price - money(self.value)
        else:
            raw = ZERO
        return max(ZERO, min(money(raw), price))


@dataclass(frozen=True)
class PromotionOutcome:
    """The promotions that applied, and what they took off."""

    final_price: Decimal
    total_discount: Decimal
    applied: tuple[str, ...] = ()
    rejected: tuple[dict, ...] = field(default_factory=tuple)
    capped: bool = False

    @property
    def discount_percentage(self) -> Decimal:
        base = money(self.final_price) + money(self.total_discount)
        if base <= ZERO:
            return ZERO
        return (money(self.total_discount) / base * HUNDRED).quantize(
            PENNY, rounding=ROUND_HALF_UP
        )


class PromotionEngine:
    """Applies promotions to a price under declared stacking rules."""

    @staticmethod
    def eligible(*, promotions: list[Promotion], branch_id: str, sku_id: str,
                 quantity: Decimal, customer_segment: str | None, on_date: date) -> list[Promotion]:
        return [
            promotion
            for promotion in promotions
            if promotion.applies_to(
                branch_id=branch_id, sku_id=sku_id, quantity=quantity,
                customer_segment=customer_segment, on_date=on_date,
            )
        ]

    @classmethod
    def apply(cls, *, base_price: Decimal, promotions: list[Promotion],
              branch_id: str, sku_id: str, quantity: Decimal = Decimal("1"),
              customer_segment: str | None = None, on_date: date | None = None,
              maximum_discount_percentage: Decimal = Decimal("100")) -> PromotionOutcome:
        """Work out the final price.

        Order is deliberate: eligibility, then stacking, then the cap. The cap
        is applied last and unconditionally, so it still holds when every
        individual promotion was configured correctly and the combination was
        not.
        """
        on_date = on_date or date.today()
        base_price = money(base_price)
        rejected: list[dict] = []

        eligible = cls.eligible(
            promotions=promotions, branch_id=branch_id, sku_id=sku_id,
            quantity=quantity, customer_segment=customer_segment, on_date=on_date,
        )
        for promotion in promotions:
            if promotion not in eligible:
                rejected.append({"code": promotion.code, "reason": "not eligible"})

        if not eligible:
            return PromotionOutcome(
                final_price=base_price, total_discount=ZERO, rejected=tuple(rejected)
            )

        ordered = sorted(eligible, key=lambda promotion: (promotion.priority, promotion.code))

        exclusive = [p for p in ordered if p.stacking == StackingRule.EXCLUSIVE]
        if exclusive:
            # The highest-priority exclusive offer runs alone.
            winner = exclusive[0]
            for promotion in ordered:
                if promotion is not winner:
                    rejected.append(
                        {"code": promotion.code, "reason": f"excluded by {winner.code}"}
                    )
            return cls._single(
                base_price=base_price, promotion=winner,
                rejected=rejected, cap=maximum_discount_percentage,
            )

        best_only = [p for p in ordered if p.stacking == StackingRule.BEST_PRICE_ONLY]
        if best_only and len(ordered) == len(best_only):
            # They compete rather than combine, so the cheapest single offer
            # wins outright.
            winner = max(best_only, key=lambda promotion: promotion.discount_on(base_price))
            for promotion in ordered:
                if promotion is not winner:
                    rejected.append(
                        {"code": promotion.code, "reason": "a better single offer applied"}
                    )
            return cls._single(
                base_price=base_price, promotion=winner,
                rejected=rejected, cap=maximum_discount_percentage,
            )

        return cls._stack(
            base_price=base_price, promotions=ordered,
            rejected=rejected, cap=maximum_discount_percentage,
        )

    @classmethod
    def _single(cls, *, base_price, promotion, rejected, cap) -> PromotionOutcome:
        discount = promotion.discount_on(base_price)
        if not promotion.has_headroom(amount=discount):
            rejected.append({"code": promotion.code, "reason": "redemption or budget exhausted"})
            return PromotionOutcome(
                final_price=base_price, total_discount=ZERO, rejected=tuple(rejected)
            )
        return cls._cap(
            base_price=base_price, discount=discount,
            applied=(promotion.code,), rejected=rejected, cap=cap,
        )

    @classmethod
    def _stack(cls, *, base_price, promotions, rejected, cap) -> PromotionOutcome:
        """Combine promotions multiplicatively, up to any stated limit.

        Each offer applies to what the previous one left, so two 20% offers
        leave 64% of the price rather than 60%. Summing the percentages is how
        a basket reaches zero with four offers that each looked reasonable.
        """
        running = base_price
        applied: list[str] = []

        limit = min(
            (p.stack_limit for p in promotions if p.stacking == StackingRule.STACKABLE_WITH_LIMIT),
            default=len(promotions),
        )

        for promotion in promotions:
            if len(applied) >= limit:
                rejected.append(
                    {"code": promotion.code, "reason": f"stack limit of {limit} reached"}
                )
                continue
            step = promotion.discount_on(running)
            if step <= ZERO:
                rejected.append({"code": promotion.code, "reason": "no discount at this price"})
                continue
            if not promotion.has_headroom(amount=step):
                rejected.append(
                    {"code": promotion.code, "reason": "redemption or budget exhausted"}
                )
                continue
            running = money(running - step)
            applied.append(promotion.code)

        return cls._cap(
            base_price=base_price, discount=money(base_price - running),
            applied=tuple(applied), rejected=rejected, cap=cap,
        )

    @staticmethod
    def _cap(*, base_price, discount, applied, rejected, cap) -> PromotionOutcome:
        """Bound the total, whatever the individual offers said.

        Absolute and last. A basket cannot be discounted past its configured
        maximum however many correctly-configured promotions apply to it.
        """
        maximum = money(base_price * (money(cap) / HUNDRED))
        capped = discount > maximum
        final_discount = min(money(discount), maximum)

        return PromotionOutcome(
            final_price=money(base_price - final_discount),
            total_discount=final_discount,
            applied=tuple(applied),
            rejected=tuple(rejected),
            capped=capped,
        )
