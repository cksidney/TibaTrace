"""Expected cash and variance.

This is the arithmetic that decides whether a cashier is asked to account for a
shortfall, so the tests are written around the ways it can wrongly accuse
someone or wrongly clear them.

Two failures dominate:

* counting non-cash tenders as till cash, which shows a cashier short by exactly
  what their customers paid by M-PESA or card;
* counting money that was never settled, or that was settled and then reversed.

Do not relax these to make a shift reconcile. A shift that does not reconcile is
the signal.
"""
from decimal import Decimal

import pytest

from apps.pos_shift.cash_control import (
    CASH_TENDERS,
    CashVariance,
    ExpectedCash,
    money,
)
from apps.pos_shift.models import CashMovement


def cash(value: str) -> Decimal:
    return Decimal(value)


def expected(**overrides) -> ExpectedCash:
    base = {
        "opening": cash("5000.00"),
        "cash_sales": cash("0.00"),
        "cash_in": cash("0.00"),
        "cash_out": cash("0.00"),
        "cash_refunds": cash("0.00"),
    }
    base.update(overrides)
    return ExpectedCash(**base)


# ─── decimal safety ──────────────────────────────────────────────────────────


class TestDecimalSafety:
    def test_money_never_goes_through_float(self):
        # Decimal(0.1) is 0.1000000000000000055511151231257827.
        assert money(0.1) == Decimal("0.10")
        assert money("0.1") == Decimal("0.10")

    def test_money_quantises_to_two_places(self):
        assert money("10.005") == Decimal("10.01")
        assert money("10.004") == Decimal("10.00")

    def test_none_is_zero(self):
        assert money(None) == Decimal("0.00")

    def test_repeated_addition_does_not_drift(self):
        # The classic float failure: 0.1 added ten times is not 1.0.
        total = Decimal("0.00")
        for _ in range(10):
            total += money("0.10")
        assert total == Decimal("1.00")


# ─── the formula ─────────────────────────────────────────────────────────────


class TestExpectedCashFormula:
    def test_opening_only(self):
        assert expected().expected == cash("5000.00")

    def test_cash_sales_add(self):
        assert expected(cash_sales=cash("2500.00")).expected == cash("7500.00")

    def test_cash_in_adds(self):
        assert expected(cash_in=cash("1000.00")).expected == cash("6000.00")

    def test_cash_out_subtracts(self):
        assert expected(cash_out=cash("1500.00")).expected == cash("3500.00")

    def test_refunds_subtract(self):
        assert expected(cash_refunds=cash("250.00")).expected == cash("4750.00")

    def test_a_full_shift(self):
        result = expected(
            opening=cash("5000.00"),
            cash_sales=cash("18450.50"),
            cash_in=cash("2000.00"),
            cash_out=cash("3000.00"),
            cash_refunds=cash("450.50"),
        )
        # 5000 + 18450.50 + 2000 - 3000 - 450.50
        assert result.expected == cash("22000.00")

    def test_every_term_is_reported_separately(self):
        # An operator disputing a shortfall needs to see which line they
        # disagree with, not a single unarguable total.
        lines = dict(expected(cash_sales=cash("100.00"), cash_out=cash("40.00")).as_lines())
        assert lines["Opening cash"] == cash("5000.00")
        assert lines["Cash sales"] == cash("100.00")
        assert lines["Cash out"] == cash("-40.00")
        assert lines["Expected closing cash"] == cash("5060.00")


# ─── what counts as cash ─────────────────────────────────────────────────────


class TestTenderClassification:
    def test_only_cash_is_till_cash(self):
        assert CASH_TENDERS == frozenset({"CASH"})

    @pytest.mark.parametrize("tender", ["MPESA", "CARD", "INSURANCE", "ACCOUNT", "VOUCHER"])
    def test_non_cash_tenders_are_excluded(self, tender):
        # Including any of these shows a cashier short by exactly the amount
        # their customers paid electronically.
        assert tender not in CASH_TENDERS

    def test_breakdown_separates_cash_from_the_rest(self):
        from apps.pos_shift.cash_control import TenderBreakdown

        breakdown = TenderBreakdown(
            by_type={"CASH": cash("1000.00"), "MPESA": cash("2500.00"), "CARD": cash("500.00")}
        )
        assert breakdown.cash == cash("1000.00")
        assert breakdown.non_cash == cash("3000.00")
        assert breakdown.total == cash("4000.00")

    def test_an_all_electronic_shift_expects_only_the_float(self):
        from apps.pos_shift.cash_control import TenderBreakdown

        breakdown = TenderBreakdown(by_type={"MPESA": cash("40000.00")})
        result = expected(cash_sales=breakdown.cash)
        # The drawer should still hold exactly the opening float.
        assert result.expected == cash("5000.00")


# ─── cash movements ──────────────────────────────────────────────────────────


class TestCashMovementDirection:
    @pytest.mark.parametrize("kind", ["CASH_IN", "FLOAT_TOP_UP"])
    def test_inflows_are_positive(self, kind):
        movement = CashMovement(kind=kind, amount=cash("500.00"))
        assert movement.signed_amount == cash("500.00")
        assert movement.affects_expected_cash is True

    @pytest.mark.parametrize("kind", ["CASH_OUT", "SAFE_DROP", "PETTY_CASH", "BANKING"])
    def test_outflows_are_negative(self, kind):
        movement = CashMovement(kind=kind, amount=cash("500.00"))
        assert movement.signed_amount == cash("-500.00")
        assert movement.affects_expected_cash is True

    @pytest.mark.parametrize("kind", ["CORRECTION", "OTHER_AUTHORISED_MOVEMENT"])
    def test_undirected_kinds_are_not_folded_in_silently(self, kind):
        # They are reported, but guessing a direction would move real money in
        # the reconciliation on the strength of a guess.
        movement = CashMovement(kind=kind, amount=cash("500.00"))
        assert movement.affects_expected_cash is False
        assert movement.signed_amount == cash("0.00")

    def test_every_kind_is_classified(self):
        classified = CashMovement.INFLOW_KINDS | CashMovement.OUTFLOW_KINDS
        undirected = {"CORRECTION", "OTHER_AUTHORISED_MOVEMENT"}
        all_kinds = {code for code, _ in CashMovement.KINDS}
        # A newly added kind must be deliberately placed, not defaulted.
        assert all_kinds == classified | undirected

    def test_a_safe_drop_reduces_expected_cash(self):
        # Money physically left the drawer for the safe.
        result = expected(cash_sales=cash("10000.00"), cash_out=cash("8000.00"))
        assert result.expected == cash("7000.00")


# ─── variance ────────────────────────────────────────────────────────────────


class TestVariance:
    def test_exact_count(self):
        variance = CashVariance(declared=cash("7000.00"), expected=cash("7000.00"))
        assert variance.difference == cash("0.00")
        assert variance.classification == "EXACT"
        assert variance.requires_explanation is False

    def test_short(self):
        variance = CashVariance(declared=cash("6900.00"), expected=cash("7000.00"))
        assert variance.difference == cash("-100.00")
        assert variance.classification == "SHORT"
        assert variance.requires_explanation is True

    def test_over(self):
        variance = CashVariance(declared=cash("7100.00"), expected=cash("7000.00"))
        assert variance.difference == cash("100.00")
        assert variance.classification == "OVER"
        # An overage is investigated too: it usually means a sale went
        # unrecorded, which is not good news.
        assert variance.requires_explanation is True

    def test_within_tolerance(self):
        variance = CashVariance(
            declared=cash("6999.00"), expected=cash("7000.00"), tolerance=cash("5.00")
        )
        assert variance.classification == "WITHIN_TOLERANCE"
        assert variance.requires_explanation is False

    def test_tolerance_is_inclusive_at_the_boundary(self):
        variance = CashVariance(
            declared=cash("6995.00"), expected=cash("7000.00"), tolerance=cash("5.00")
        )
        assert variance.classification == "WITHIN_TOLERANCE"

    def test_just_outside_tolerance_is_reported(self):
        variance = CashVariance(
            declared=cash("6994.99"), expected=cash("7000.00"), tolerance=cash("5.00")
        )
        assert variance.classification == "SHORT"

    def test_tolerance_applies_symmetrically(self):
        over = CashVariance(
            declared=cash("7005.00"), expected=cash("7000.00"), tolerance=cash("5.00")
        )
        assert over.classification == "WITHIN_TOLERANCE"

    def test_zero_tolerance_reports_a_single_cent(self):
        variance = CashVariance(declared=cash("6999.99"), expected=cash("7000.00"))
        assert variance.classification == "SHORT"
        assert variance.difference == cash("-0.01")


# ─── the scenario the whole module exists to prevent ─────────────────────────


class TestElectronicPaymentsDoNotAccuseTheCashier:
    def test_a_busy_mpesa_day_does_not_look_like_theft(self):
        """A cashier taking mostly M-PESA must not appear massively short.

        Counting electronic tenders as till cash is the single most damaging
        error this module can make: it produces a confident, specific, entirely
        false accusation against a named person.
        """
        from apps.pos_shift.cash_control import TenderBreakdown

        breakdown = TenderBreakdown(
            by_type={"CASH": cash("3000.00"), "MPESA": cash("47000.00"), "CARD": cash("12000.00")}
        )
        result = expected(opening=cash("5000.00"), cash_sales=breakdown.cash)

        assert result.expected == cash("8000.00")

        # The cashier counts the drawer and finds exactly that.
        variance = CashVariance(declared=cash("8000.00"), expected=result.expected)
        assert variance.classification == "EXACT"

        # Had the electronic tenders been included, they would have appeared
        # 59,000 short.
        wrong = expected(opening=cash("5000.00"), cash_sales=breakdown.total)
        assert wrong.expected - result.expected == cash("59000.00")
