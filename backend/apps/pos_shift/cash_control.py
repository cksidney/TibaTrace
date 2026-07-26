"""Expected cash, and the variance against what was counted.

This is the number that decides whether a cashier is asked to explain a
shortfall. Two properties therefore govern the whole module.

**Only physical cash counts.** M-PESA, card, insurance receivables and account
sales never touched the drawer, so including any of them would show a cashier
short by exactly the amount their customers paid electronically. The tender
allowlist below is explicit, and `CASH_TENDERS` is deliberately narrow: a tender
type added elsewhere is excluded from till cash until somebody decides
otherwise.

**Only settled money counts.** An initiated M-PESA push and a failed card
authorisation are not cash. `PaymentTender.effective_settled` -- settled minus
reversed -- is the authoritative figure, so a reversal removes money from
expected cash exactly as it removed it from the drawer.

Everything is `Decimal`. Floating point in a cash reconciliation produces
variances of a few cents that nobody can explain and everybody learns to ignore,
which is how a real shortfall gets missed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from apps.prescription.payment_models import PaymentTender

from .models import ZERO, CashDeclaration, CashMovement, RegisterSession

#: Tender types that put notes and coins in the drawer. Only CASH does.
CASH_TENDERS = frozenset({"CASH"})

#: Reported on the X/Z report but never added to physical expected cash.
NON_CASH_TENDERS = frozenset({"CARD", "MPESA"})

PENNY = Decimal("0.01")


def money(value) -> Decimal:
    """Coerce to a two-place Decimal, never via float."""
    if isinstance(value, Decimal):
        amount = value
    elif value is None:
        amount = ZERO
    else:
        # str() first: Decimal(float) inherits the float's binary error.
        amount = Decimal(str(value))
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TenderBreakdown:
    """Settled value by tender type, for the report's tender section."""

    by_type: dict[str, Decimal] = field(default_factory=dict)

    @property
    def cash(self) -> Decimal:
        return money(sum((v for k, v in self.by_type.items() if k in CASH_TENDERS), ZERO))

    @property
    def non_cash(self) -> Decimal:
        return money(sum((v for k, v in self.by_type.items() if k not in CASH_TENDERS), ZERO))

    @property
    def total(self) -> Decimal:
        return money(sum(self.by_type.values(), ZERO))


@dataclass(frozen=True)
class ExpectedCash:
    """The drawer reconciliation, with every term kept separately.

    A single total would be unarguable in the wrong way: an operator disputing a
    shortfall needs to see which line they disagree with.
    """

    opening: Decimal
    cash_sales: Decimal
    cash_in: Decimal
    cash_out: Decimal
    cash_refunds: Decimal

    @property
    def expected(self) -> Decimal:
        return money(self.opening + self.cash_sales + self.cash_in - self.cash_out - self.cash_refunds)

    def as_lines(self) -> list[tuple[str, Decimal]]:
        return [
            ("Opening cash", self.opening),
            ("Cash sales", self.cash_sales),
            ("Cash in", self.cash_in),
            ("Cash out", -self.cash_out),
            ("Cash refunds", -self.cash_refunds),
            ("Expected closing cash", self.expected),
        ]


@dataclass(frozen=True)
class CashVariance:
    """Counted minus expected, and what it means."""

    declared: Decimal
    expected: Decimal
    #: Absolute tolerance from tenant policy.
    tolerance: Decimal = ZERO

    @property
    def difference(self) -> Decimal:
        """Positive is over, negative is short."""
        return money(self.declared - self.expected)

    @property
    def classification(self) -> str:
        difference = self.difference
        if difference == ZERO:
            return "EXACT"
        if abs(difference) <= self.tolerance:
            return "WITHIN_TOLERANCE"
        return "OVER" if difference > ZERO else "SHORT"

    @property
    def requires_explanation(self) -> bool:
        return self.classification in {"OVER", "SHORT"}


class CashControlService:
    """Derives cash figures from authoritative ledger rows."""

    @staticmethod
    def opening_cash(*, session: RegisterSession) -> Decimal:
        """The confirmed opening declaration, or zero if none was made.

        The latest attempt wins, so a corrected opening count supersedes the
        first without either being edited.
        """
        declaration = (
            CashDeclaration.all_objects.filter(
                tenant_id=session.tenant_id,
                register_session=session,
                kind="OPENING",
                confirmed_at__isnull=False,
            )
            .order_by("-attempt")
            .first()
        )
        return money(declaration.declared_amount) if declaration else ZERO

    @staticmethod
    def tender_breakdown(*, session: RegisterSession) -> TenderBreakdown:
        """Settled value per tender type for this session.

        Reads `settled_amount - reversed_amount` so a reversal is netted off
        rather than leaving the till expecting money that was handed back.
        """
        by_type: dict[str, Decimal] = {}
        tenders = PaymentTender.all_objects.filter(
            tenant_id=session.tenant_id, register_session_id=session.pk
        ).values("tender_type", "settled_amount", "reversed_amount")

        for row in tenders:
            effective = money(row["settled_amount"]) - money(row["reversed_amount"])
            key = row["tender_type"]
            by_type[key] = money(by_type.get(key, ZERO) + effective)
        return TenderBreakdown(by_type=by_type)

    @staticmethod
    def movement_totals(*, session: RegisterSession) -> tuple[Decimal, Decimal]:
        """(cash in, cash out) from authorised movements.

        Returns both as positive magnitudes; the caller subtracts the outflow.
        Movements with no inherent direction are excluded rather than guessed
        at.
        """
        cash_in = ZERO
        cash_out = ZERO
        for movement in CashMovement.all_objects.filter(
            tenant_id=session.tenant_id, register_session=session
        ):
            if not movement.affects_expected_cash:
                continue
            if movement.kind in CashMovement.INFLOW_KINDS:
                cash_in += money(movement.amount)
            else:
                cash_out += money(movement.amount)
        return money(cash_in), money(cash_out)

    @classmethod
    def expected_cash(cls, *, session: RegisterSession, cash_refunds: Decimal | None = None) -> ExpectedCash:
        """Assemble the drawer reconciliation for a session."""
        breakdown = cls.tender_breakdown(session=session)
        cash_in, cash_out = cls.movement_totals(session=session)
        return ExpectedCash(
            opening=cls.opening_cash(session=session),
            cash_sales=breakdown.cash,
            cash_in=cash_in,
            cash_out=cash_out,
            cash_refunds=money(cash_refunds),
        )

    @staticmethod
    def variance(*, declared: Decimal, expected: Decimal, tolerance: Decimal = ZERO) -> CashVariance:
        return CashVariance(
            declared=money(declared), expected=money(expected), tolerance=money(tolerance)
        )
