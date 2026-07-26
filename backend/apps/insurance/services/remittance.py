"""Remittance import, matching and claim closure.

The rule this module protects: **a claim is paid when money arrives, not when an
insurer approves it.**

Approval and payment are separated by weeks, and insurers routinely pay less
than they approved -- withholding, contractual adjustment, recovery against an
earlier overpayment, or simple error. A claim marked paid on approval reports
revenue that has not been collected and removes the one signal that would have
prompted anybody to chase it.

The second rule: **differences are never forced to zero.** An underpayment is
information. Writing it off automatically converts a recoverable shortfall into
a silent loss, one claim at a time, and nobody ever sees the pattern.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import (
    ClaimReconciliation,
    ClaimReconciliationException,
    InsurancePayment,
    InsurancePaymentAllocation,
    InsuranceRemittance,
    InsuranceRemittanceLine,
    PrescriptionClaim,
)

ZERO = Decimal("0.00")
PENNY = Decimal("0.01")


def money(value) -> Decimal:
    if value is None:
        return ZERO
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


class MatchOutcome:
    """How a remittance line related to the claim it names."""

    MATCHED = "MATCHED"
    UNDERPAID = "UNDERPAID"
    OVERPAID = "OVERPAID"
    UNMATCHED = "UNMATCHED"
    DUPLICATE = "DUPLICATE"
    REVERSED = "REVERSED"


class DuplicateRemittance(ValidationError):
    """This remittance has already been imported."""


class RemittanceService:
    """Imports insurer payments and matches them to claims."""

    @staticmethod
    def already_imported(*, tenant_id, insurer, remittance_number: str) -> bool:
        return InsuranceRemittance.all_objects.filter(
            tenant_id=tenant_id, insurer=insurer, remittance_number=remittance_number
        ).exists()

    @classmethod
    @transaction.atomic
    def import_remittance(cls, *, tenant_id, insurer, remittance_number: str,
                          total_amount: Decimal, payment_reference: str,
                          remittance_date, lines: list[dict]) -> InsuranceRemittance:
        """Record an insurer payment advice.

        Refuses a remittance number already imported for this insurer. A
        spreadsheet re-uploaded after a partial failure would otherwise pay
        every claim on it twice, and the second allocation looks exactly like
        the first.
        """
        if cls.already_imported(
            tenant_id=tenant_id, insurer=insurer, remittance_number=remittance_number
        ):
            raise DuplicateRemittance(
                f"Remittance {remittance_number} has already been imported for this insurer."
            )

        remittance = InsuranceRemittance.all_objects.create(
            tenant_id=tenant_id,
            insurer=insurer,
            remittance_number=remittance_number,
            total_remitted_amount=money(total_amount),
            payment_reference=payment_reference,
            remittance_date=remittance_date,
            status="IMPORTED",
        )

        for line in lines:
            claim = cls._find_claim(tenant_id=tenant_id, reference=line.get("claim_reference"))
            InsuranceRemittanceLine.all_objects.create(
                tenant_id=tenant_id,
                remittance=remittance,
                claim=claim,
                claimed_amount=money(line.get("claimed_amount")),
                paid_amount=money(line.get("paid_amount")),
                adjustment_amount=money(line.get("adjustment_amount")),
                # An unidentifiable line is held as unmatched rather than
                # dropped. Money that arrived and cannot be placed is exactly
                # what somebody must investigate.
                status=MatchOutcome.MATCHED if claim else MatchOutcome.UNMATCHED,
            )
        return remittance

    @staticmethod
    def _find_claim(*, tenant_id, reference):
        if not reference:
            return None
        return PrescriptionClaim.all_objects.filter(
            tenant_id=tenant_id, claim_number=str(reference)
        ).first()

    # ------------------------------------------------------------- matching

    @staticmethod
    def classify(*, approved: Decimal, paid: Decimal, tolerance: Decimal = ZERO) -> str:
        """Compare what the insurer approved with what they actually sent."""
        approved = money(approved)
        paid = money(paid)
        difference = paid - approved

        if difference == ZERO:
            return MatchOutcome.MATCHED
        if abs(difference) <= money(tolerance):
            return MatchOutcome.MATCHED
        return MatchOutcome.OVERPAID if difference > ZERO else MatchOutcome.UNDERPAID

    @classmethod
    @transaction.atomic
    def reconcile(cls, *, remittance: InsuranceRemittance, actor=None,
                  tolerance: Decimal = ZERO) -> list[ClaimReconciliation]:
        """Match every line, allocate payment, and raise exceptions for the rest.

        Differences are recorded, never absorbed. An underpayment written off
        automatically becomes a silent loss repeated across thousands of claims
        that nobody ever aggregates.
        """
        reconciliations: list[ClaimReconciliation] = []
        tenant_id = remittance.tenant_id

        for line in InsuranceRemittanceLine.all_objects.filter(
            tenant_id=tenant_id, remittance=remittance
        ).select_related("claim"):
            claim = line.claim
            if claim is None:
                ClaimReconciliationException.all_objects.create(
                    tenant_id=tenant_id,
                    claim=None,
                    remittance=remittance,
                    exception_type=MatchOutcome.UNMATCHED,
                    variance_amount=money(line.paid_amount),
                    notes="Remittance line names no claim this tenant holds.",
                )
                continue

            outcome = cls.classify(
                approved=claim.approved_amount, paid=line.paid_amount, tolerance=tolerance
            )
            variance = money(line.paid_amount) - money(claim.approved_amount)

            reconciliation = ClaimReconciliation.all_objects.create(
                tenant_id=tenant_id,
                claim=claim,
                remittance=remittance,
                status=outcome,
                reconciled_amount=money(line.paid_amount),
                variance_amount=variance,
                reconciled_by=actor,
            )
            reconciliations.append(reconciliation)

            if outcome != MatchOutcome.MATCHED:
                ClaimReconciliationException.all_objects.create(
                    tenant_id=tenant_id,
                    claim=claim,
                    remittance=remittance,
                    exception_type=outcome,
                    variance_amount=variance,
                    notes=(
                        f"Insurer approved {money(claim.approved_amount)} "
                        f"and paid {money(line.paid_amount)}."
                    ),
                )

            cls._allocate(remittance=remittance, claim=claim, amount=line.paid_amount)
            line.status = outcome
            line.save(update_fields=["status", "updated_at"])

        remittance.status = "RECONCILED"
        remittance.save(update_fields=["status", "updated_at"])
        return reconciliations

    # ------------------------------------------------------------ allocation

    @classmethod
    def _allocate(cls, *, remittance: InsuranceRemittance, claim: PrescriptionClaim,
                  amount: Decimal) -> InsurancePaymentAllocation | None:
        """Record money received against a claim and update its payment state.

        This is the only place a claim becomes PAID, and it needs money to have
        arrived. An approval never reaches here.
        """
        amount = money(amount)
        if amount <= ZERO:
            return None

        payment = InsurancePayment.all_objects.create(
            tenant_id=claim.tenant_id,
            remittance=remittance,
            payment_reference=remittance.payment_reference,
            amount=amount,
            payment_date=remittance.remittance_date,
        )
        allocation = InsurancePaymentAllocation.all_objects.create(
            tenant_id=claim.tenant_id,
            payment=payment,
            claim=claim,
            allocated_amount=amount,
        )

        claim.paid_amount = money(claim.paid_amount) + amount
        claim.payment_state = cls.payment_state_for(
            paid=claim.paid_amount, approved=claim.approved_amount
        )
        claim.reconciliation_state = (
            PrescriptionClaim.ReconciliationState.MATCHED
            if claim.payment_state == PrescriptionClaim.PaymentState.PAID
            else PrescriptionClaim.ReconciliationState.PARTIALLY_MATCHED
        )
        claim.save(
            update_fields=["paid_amount", "payment_state", "reconciliation_state", "updated_at"]
        )
        return allocation

    @staticmethod
    def payment_state_for(*, paid: Decimal, approved: Decimal) -> str:
        """Payment state from money actually received.

        A claim approved for nothing is not paid however much arrives against
        it -- that is an overpayment needing investigation, not a settled claim.
        """
        paid = money(paid)
        approved = money(approved)

        if paid <= ZERO:
            return PrescriptionClaim.PaymentState.UNPAID
        if approved <= ZERO:
            return PrescriptionClaim.PaymentState.PARTIALLY_PAID
        if paid >= approved:
            return PrescriptionClaim.PaymentState.PAID
        return PrescriptionClaim.PaymentState.PARTIALLY_PAID


class InsuranceReceivableService:
    """What the insurer owes, derived from approvals and payments."""

    @staticmethod
    def outstanding(*, claim: PrescriptionClaim) -> Decimal:
        """Approved minus received, never below zero.

        Reads `approved_amount`, so a claim that was submitted, acknowledged and
        never decided contributes nothing. Transport acceptance is not a debt.
        """
        return max(ZERO, money(claim.approved_amount) - money(claim.paid_amount))

    @staticmethod
    def is_receivable(*, claim: PrescriptionClaim) -> bool:
        """Whether this claim represents money the insurer has agreed to pay."""
        return claim.adjudication_state in {
            PrescriptionClaim.AdjudicationState.APPROVED,
            PrescriptionClaim.AdjudicationState.PARTIALLY_APPROVED,
        } and money(claim.approved_amount) > ZERO

    @classmethod
    def total_outstanding(cls, *, tenant_id, insurer=None) -> Decimal:
        """Aged debt across claims. Only approved claims count."""
        claims = PrescriptionClaim.all_objects.filter(
            tenant_id=tenant_id,
            adjudication_state__in=[
                PrescriptionClaim.AdjudicationState.APPROVED,
                PrescriptionClaim.AdjudicationState.PARTIALLY_APPROVED,
            ],
        )
        if insurer is not None:
            claims = claims.filter(insurer=insurer)
        return money(sum((cls.outstanding(claim=claim) for claim in claims), ZERO))

    @staticmethod
    def posting_lines(*, claim: PrescriptionClaim) -> list[dict]:
        """The finance entries an approval implies.

        Returned for the finance service to post; nothing here writes a journal.
        The patient co-payment is deliberately absent -- it settles through the
        payment ledger as a tender the patient handed over, and folding it in
        here would double-count it as both cash and receivable.
        """
        if not InsuranceReceivableService.is_receivable(claim=claim):
            return []
        approved = money(claim.approved_amount)
        disallowed = money(claim.claimed_gross_amount) - approved - money(claim.patient_copay_amount)
        lines = [
            {"account": "INSURANCE_RECEIVABLE", "direction": "DEBIT", "amount": approved},
            {"account": "DISPENSING_REVENUE", "direction": "CREDIT", "amount": approved},
        ]
        if disallowed > ZERO:
            # The gap between asked and allowed. Somebody must account for it;
            # it does not simply evaporate.
            lines.append(
                {"account": "CONTRACTUAL_ADJUSTMENT", "direction": "DEBIT", "amount": disallowed}
            )
        return lines
