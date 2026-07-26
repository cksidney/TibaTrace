"""Remittance, reconciliation and insurer receivables.

Two rules, each corresponding to money quietly going missing:

* a claim is paid when money arrives, not when an insurer approves it;
* differences are recorded, never forced to zero.

An underpayment written off automatically becomes a silent loss repeated across
thousands of claims that nobody ever aggregates.
"""
from decimal import Decimal

import pytest

from apps.insurance.models import PrescriptionClaim
from apps.insurance.services.remittance import (
    InsuranceReceivableService,
    MatchOutcome,
    RemittanceService,
    money,
)


def cash(value: str) -> Decimal:
    return Decimal(value)


class FakeClaim:
    """Stands in for a claim row where only the money matters."""

    def __init__(self, *, approved="0.00", paid="0.00", gross="0.00", copay="0.00",
                 adjudication_state=PrescriptionClaim.AdjudicationState.APPROVED):
        self.approved_amount = cash(approved)
        self.paid_amount = cash(paid)
        self.claimed_gross_amount = cash(gross)
        self.patient_copay_amount = cash(copay)
        self.adjudication_state = adjudication_state


# ─── matching ────────────────────────────────────────────────────────────────


class TestClassification:
    def test_exact_payment_matches(self):
        assert (
            RemittanceService.classify(approved=cash("1000.00"), paid=cash("1000.00"))
            == MatchOutcome.MATCHED
        )

    def test_short_payment_is_underpaid(self):
        # Recorded, not absorbed.
        assert (
            RemittanceService.classify(approved=cash("1000.00"), paid=cash("850.00"))
            == MatchOutcome.UNDERPAID
        )

    def test_excess_payment_is_overpaid(self):
        # Usually a recovery against something else, and always worth knowing.
        assert (
            RemittanceService.classify(approved=cash("1000.00"), paid=cash("1200.00"))
            == MatchOutcome.OVERPAID
        )

    def test_a_single_cent_is_reported_at_zero_tolerance(self):
        assert (
            RemittanceService.classify(approved=cash("1000.00"), paid=cash("999.99"))
            == MatchOutcome.UNDERPAID
        )

    def test_tolerance_absorbs_only_what_it_is_set_to(self):
        assert (
            RemittanceService.classify(
                approved=cash("1000.00"), paid=cash("999.00"), tolerance=cash("1.00")
            )
            == MatchOutcome.MATCHED
        )
        assert (
            RemittanceService.classify(
                approved=cash("1000.00"), paid=cash("998.99"), tolerance=cash("1.00")
            )
            == MatchOutcome.UNDERPAID
        )

    def test_tolerance_is_symmetric(self):
        assert (
            RemittanceService.classify(
                approved=cash("1000.00"), paid=cash("1001.00"), tolerance=cash("1.00")
            )
            == MatchOutcome.MATCHED
        )


# ─── approval is not payment ─────────────────────────────────────────────────


class TestPaymentState:
    def test_nothing_received_is_unpaid(self):
        assert (
            RemittanceService.payment_state_for(paid=cash("0.00"), approved=cash("1000.00"))
            == PrescriptionClaim.PaymentState.UNPAID
        )

    def test_part_received_is_partially_paid(self):
        assert (
            RemittanceService.payment_state_for(paid=cash("400.00"), approved=cash("1000.00"))
            == PrescriptionClaim.PaymentState.PARTIALLY_PAID
        )

    def test_full_receipt_is_paid(self):
        assert (
            RemittanceService.payment_state_for(paid=cash("1000.00"), approved=cash("1000.00"))
            == PrescriptionClaim.PaymentState.PAID
        )

    def test_an_approval_alone_never_produces_paid(self):
        """The whole point. Approval and payment are weeks apart, and insurers
        routinely pay less than they approved."""
        for approved in ["1000.00", "50000.00"]:
            assert (
                RemittanceService.payment_state_for(paid=cash("0.00"), approved=cash(approved))
                != PrescriptionClaim.PaymentState.PAID
            )

    def test_money_against_a_claim_approved_for_nothing_is_not_settled(self):
        # That is an overpayment needing investigation, not a settled claim.
        assert (
            RemittanceService.payment_state_for(paid=cash("500.00"), approved=cash("0.00"))
            == PrescriptionClaim.PaymentState.PARTIALLY_PAID
        )


# ─── receivables ─────────────────────────────────────────────────────────────


class TestReceivables:
    def test_outstanding_is_approved_minus_received(self):
        claim = FakeClaim(approved="1000.00", paid="400.00")
        assert InsuranceReceivableService.outstanding(claim=claim) == cash("600.00")

    def test_a_fully_paid_claim_owes_nothing(self):
        claim = FakeClaim(approved="1000.00", paid="1000.00")
        assert InsuranceReceivableService.outstanding(claim=claim) == cash("0.00")

    def test_an_overpaid_claim_does_not_owe_a_negative(self):
        claim = FakeClaim(approved="1000.00", paid="1200.00")
        assert InsuranceReceivableService.outstanding(claim=claim) == cash("0.00")

    def test_a_pending_claim_is_not_a_receivable(self):
        """Transport acceptance is not a debt.

        A claim the insurer holds and has said nothing about is not money owed,
        and booking it reports revenue nobody agreed to pay.
        """
        claim = FakeClaim(
            approved="0.00",
            gross="1000.00",
            adjudication_state=PrescriptionClaim.AdjudicationState.PENDING,
        )
        assert InsuranceReceivableService.is_receivable(claim=claim) is False
        assert InsuranceReceivableService.outstanding(claim=claim) == cash("0.00")

    def test_a_rejected_claim_is_not_a_receivable(self):
        claim = FakeClaim(
            approved="0.00",
            adjudication_state=PrescriptionClaim.AdjudicationState.REJECTED,
        )
        assert InsuranceReceivableService.is_receivable(claim=claim) is False

    def test_an_approved_claim_is_a_receivable(self):
        claim = FakeClaim(approved="1000.00")
        assert InsuranceReceivableService.is_receivable(claim=claim) is True

    def test_a_partial_approval_is_a_receivable_for_its_approved_part(self):
        claim = FakeClaim(
            approved="800.00",
            gross="1000.00",
            adjudication_state=PrescriptionClaim.AdjudicationState.PARTIALLY_APPROVED,
        )
        assert InsuranceReceivableService.is_receivable(claim=claim) is True
        assert InsuranceReceivableService.outstanding(claim=claim) == cash("800.00")


# ─── finance postings ────────────────────────────────────────────────────────


class TestPostings:
    def test_a_pending_claim_posts_nothing(self):
        claim = FakeClaim(
            approved="0.00",
            adjudication_state=PrescriptionClaim.AdjudicationState.PENDING,
        )
        assert InsuranceReceivableService.posting_lines(claim=claim) == []

    def test_an_approval_debits_receivable_and_credits_revenue(self):
        claim = FakeClaim(approved="1000.00", gross="1000.00")
        lines = InsuranceReceivableService.posting_lines(claim=claim)
        accounts = {line["account"]: line for line in lines}
        assert accounts["INSURANCE_RECEIVABLE"]["direction"] == "DEBIT"
        assert accounts["INSURANCE_RECEIVABLE"]["amount"] == cash("1000.00")
        assert accounts["DISPENSING_REVENUE"]["direction"] == "CREDIT"

    def test_the_gap_between_asked_and_allowed_is_posted(self):
        # 1000 claimed, 100 patient co-pay, 750 approved: 150 contractual.
        claim = FakeClaim(approved="750.00", gross="1000.00", copay="100.00")
        lines = InsuranceReceivableService.posting_lines(claim=claim)
        adjustment = next(
            line for line in lines if line["account"] == "CONTRACTUAL_ADJUSTMENT"
        )
        assert adjustment["amount"] == cash("150.00")

    def test_the_patient_copayment_is_not_posted_as_a_receivable(self):
        """It settles through the payment ledger as a tender the patient handed
        over. Folding it in here counts it twice."""
        claim = FakeClaim(approved="750.00", gross="1000.00", copay="100.00")
        lines = InsuranceReceivableService.posting_lines(claim=claim)
        assert all("COPAY" not in line["account"] for line in lines)
        assert all("PATIENT" not in line["account"] for line in lines)

    def test_no_adjustment_line_when_everything_was_allowed(self):
        claim = FakeClaim(approved="900.00", gross="1000.00", copay="100.00")
        lines = InsuranceReceivableService.posting_lines(claim=claim)
        assert all(line["account"] != "CONTRACTUAL_ADJUSTMENT" for line in lines)


# ─── duplicate protection ────────────────────────────────────────────────────


class TestDuplicateRemittance:
    def test_the_service_exposes_a_duplicate_guard(self):
        # A spreadsheet re-uploaded after a partial failure would otherwise pay
        # every claim on it twice, and the second allocation looks exactly like
        # the first.
        assert hasattr(RemittanceService, "already_imported")
        from apps.insurance.services.remittance import DuplicateRemittance

        assert issubclass(DuplicateRemittance, Exception)


class TestMoney:
    def test_money_never_goes_through_float(self):
        assert money(0.1) == cash("0.10")

    def test_none_is_zero(self):
        assert money(None) == cash("0.00")

    @pytest.mark.parametrize("value,expected", [("10.005", "10.01"), ("10.004", "10.00")])
    def test_rounding_is_half_up(self, value, expected):
        assert money(value) == cash(expected)
