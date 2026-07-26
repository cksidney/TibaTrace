"""Deterministic price resolution.

One item may lawfully carry different prices in different branches, for
different customers, under different insurers, during a promotion. Resolution
decides which one applies, and the whole design rests on three rules.

**Precedence is total and explicit.** Every source has a distinct rank. Two
sources can never tie, because a tie means the price depends on dictionary
ordering or row insertion order -- and a price that changes when rows are
reordered is a price nobody can defend to a customer or an auditor.

**Ambiguity fails closed.** Two active branch overrides for one item on one day
is a configuration error, not a coin toss. Resolution refuses rather than
picking, because picking hides the error until somebody notices the takings are
wrong.

**The trace is part of the answer.** A resolved price carries why it won and
what it beat. Without that, "why is this 650 here and 600 there" is
unanswerable, and the usual outcome is somebody overriding the price manually
and moving on.

Money is Decimal. A price that drifts in binary produces receipts whose lines do
not add to their total.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
PENNY = Decimal("0.01")


def money(value) -> Decimal:
    """Two-place Decimal, never via float."""
    if value is None:
        return ZERO
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


class PriceSource:
    """Where a price came from.

    The numeric rank is the precedence. Lower wins. Values are spaced so a new
    source can be inserted between two existing ones without renumbering the
    rest -- renumbering would silently change which price wins for every
    tenant.
    """

    MANUAL_OVERRIDE = ("MANUAL_OVERRIDE", 10)
    INSURANCE_TARIFF = ("INSURANCE_TARIFF", 20)
    CUSTOMER_CONTRACT = ("CUSTOMER_CONTRACT", 30)
    CUSTOMER_SEGMENT = ("CUSTOMER_SEGMENT", 40)
    BRANCH_PROMOTION = ("BRANCH_PROMOTION", 50)
    BRANCH_PRICE = ("BRANCH_PRICE", 60)
    BRANCH_GROUP_PRICE = ("BRANCH_GROUP_PRICE", 70)
    TENANT_PROMOTION = ("TENANT_PROMOTION", 80)
    TENANT_PRICE = ("TENANT_PRICE", 90)
    BASE_FALLBACK = ("BASE_FALLBACK", 100)

    @classmethod
    def all_sources(cls) -> list[tuple[str, int]]:
        return [
            value
            for name, value in vars(cls).items()
            if not name.startswith("_") and isinstance(value, tuple)
        ]


class PricingError(Exception):
    """Resolution could not produce a defensible price."""


class AmbiguousPricing(PricingError):
    """Two sources of equal precedence both apply.

    Deliberately fatal. Choosing between them would make the price depend on
    row order.
    """


class NoPriceFound(PricingError):
    """Nothing applies.

    Also fatal. A missing price is not a free item, and defaulting to zero has
    sold stock for nothing more than once in this industry.
    """


@dataclass(frozen=True)
class PriceCandidate:
    """One applicable price, before precedence is applied."""

    source: str
    rank: int
    unit_price: Decimal
    reference: str = ""
    version: str = ""
    currency: str = "KES"
    effective_from: date | None = None
    effective_to: date | None = None
    minimum_quantity: Decimal = Decimal("1")
    tax_inclusive: bool = True

    def applies_on(self, service_date: date) -> bool:
        if self.effective_from and service_date < self.effective_from:
            return False
        if self.effective_to and service_date > self.effective_to:
            return False
        return True

    def applies_to_quantity(self, quantity: Decimal) -> bool:
        return Decimal(str(quantity)) >= Decimal(str(self.minimum_quantity))


@dataclass(frozen=True)
class ResolvedPrice:
    """The answer, with its justification."""

    unit_price: Decimal
    source: str
    reference: str
    currency: str
    version: str = ""
    tax_inclusive: bool = True
    #: Every candidate that applied, ranked, with the winner first. This is what
    #: makes a price explicable rather than merely correct.
    considered: tuple[dict, ...] = field(default_factory=tuple)
    context_hash: str = ""

    @property
    def rejected(self) -> tuple[dict, ...]:
        return self.considered[1:]

    def explain(self) -> str:
        if not self.rejected:
            return f"{self.source} at {self.unit_price}; no other source applied."
        beaten = ", ".join(
            f"{item['source']} at {item['unit_price']}" for item in self.rejected
        )
        return f"{self.source} at {self.unit_price}, taking precedence over {beaten}."


@dataclass(frozen=True)
class PricingContext:
    """Everything resolution is allowed to depend on.

    A branch price cannot be resolved from an item alone, so branch and service
    date are required. Resolving without them is how one branch's price ends up
    on another branch's receipt.
    """

    tenant_id: str
    branch_id: str
    sku_id: str
    service_date: date
    quantity: Decimal = Decimal("1")
    currency: str = "KES"
    customer_id: str | None = None
    customer_segment: str | None = None
    insurer_id: str | None = None
    insurance_plan_id: str | None = None
    branch_group_id: str | None = None
    transaction_type: str = "RETAIL"

    def __post_init__(self):
        if not self.tenant_id:
            raise PricingError("Price resolution requires a tenant.")
        if not self.branch_id:
            raise PricingError(
                "Price resolution requires a branch. The same item may lawfully "
                "cost different amounts at different branches, so an item alone "
                "does not determine a price."
            )
        if not self.sku_id:
            raise PricingError("Price resolution requires an item.")
        if self.service_date is None:
            raise PricingError(
                "Price resolution requires a service date. A price that was "
                "correct today may not have been correct for a backdated sale."
            )

    def digest(self) -> str:
        """A stable fingerprint of the inputs.

        Stored alongside an applied price so a later reader can tell whether
        the context that produced it still holds.
        """
        import hashlib

        material = "|".join(
            str(part)
            for part in (
                self.tenant_id, self.branch_id, self.sku_id, self.service_date,
                self.quantity, self.currency, self.customer_id, self.customer_segment,
                self.insurer_id, self.insurance_plan_id, self.branch_group_id,
                self.transaction_type,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


class PriceResolutionService:
    """Chooses one price from the candidates that apply."""

    @staticmethod
    def applicable(candidates: list[PriceCandidate], context: PricingContext) -> list[PriceCandidate]:
        """Candidates valid for this context.

        Filters on date, quantity band and currency. A candidate in another
        currency is dropped rather than converted: silently resolving a price
        book denominated in dollars against a shilling till is worse than
        finding no price at all.
        """
        return [
            candidate
            for candidate in candidates
            if candidate.applies_on(context.service_date)
            and candidate.applies_to_quantity(context.quantity)
            and candidate.currency == context.currency
        ]

    @classmethod
    def resolve(cls, *, candidates: list[PriceCandidate], context: PricingContext) -> ResolvedPrice:
        """Resolve, or refuse.

        Never returns a guess. The two refusals -- nothing applies, and two
        things apply equally -- are both errors somebody must fix, and both are
        cheaper to fix at the till than to discover in a month's takings.
        """
        applicable = cls.applicable(candidates, context)
        if not applicable:
            raise NoPriceFound(
                f"No price applies to item {context.sku_id} at branch "
                f"{context.branch_id} on {context.service_date}. A missing price "
                "is not a free item."
            )

        ordered = sorted(applicable, key=lambda candidate: (candidate.rank, candidate.source))
        best_rank = ordered[0].rank
        tied = [candidate for candidate in ordered if candidate.rank == best_rank]

        if len(tied) > 1:
            sources = ", ".join(
                f"{candidate.source} ({candidate.reference or 'unreferenced'}) "
                f"at {money(candidate.unit_price)}"
                for candidate in tied
            )
            raise AmbiguousPricing(
                f"{len(tied)} price sources of equal precedence apply to item "
                f"{context.sku_id} at branch {context.branch_id}: {sources}. "
                "Resolution will not choose between them; correct the pricing "
                "configuration."
            )

        winner = ordered[0]
        return ResolvedPrice(
            unit_price=money(winner.unit_price),
            source=winner.source,
            reference=winner.reference,
            currency=winner.currency,
            version=winner.version,
            tax_inclusive=winner.tax_inclusive,
            considered=tuple(
                {
                    "source": candidate.source,
                    "rank": candidate.rank,
                    "unit_price": str(money(candidate.unit_price)),
                    "reference": candidate.reference,
                }
                for candidate in ordered
            ),
            context_hash=context.digest(),
        )

    @staticmethod
    def line_total(*, unit_price: Decimal, quantity: Decimal) -> Decimal:
        """Extended line value.

        Rounds once, at the end. Rounding the unit price and then multiplying
        compounds the rounding error across the quantity, which is how a
        hundred-unit line ends up a shilling out from the same line priced by
        hand.
        """
        raw = Decimal(str(unit_price)) * Decimal(str(quantity))
        return raw.quantize(PENNY, rounding=ROUND_HALF_UP)


def ranks_are_unique() -> bool:
    """Whether every source has a distinct precedence.

    Asserted by the tests. Two sources sharing a rank would make every
    resolution between them ambiguous, which turns a configuration guarantee
    into a runtime failure for every tenant at once.
    """
    ranks = [rank for _, rank in PriceSource.all_sources()]
    return len(ranks) == len(set(ranks))
