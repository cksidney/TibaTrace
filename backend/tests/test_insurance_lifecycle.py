"""Rejection, resubmission and reversal.

One rule underneath all three: a correction adds a record, it never edits the
one that was wrong. The insurer holds a copy of what we sent; editing ours so
the two disagree destroys the only evidence of what was actually claimed.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.insurance.adapters.base import AdapterResult, BusinessState, TransportState
from apps.insurance.services.lifecycle import (
    CANONICAL_REJECTION_REASONS,
    RESUBMITTABLE_REASONS,
    ClaimReversalService,
    RejectionService,
    canonical_reason,
    money,
)


def cash(value: str) -> Decimal:
    return Decimal(value)


# ─── rejection vocabulary ────────────────────────────────────────────────────


class TestCanonicalReasons:
    def test_insurer_codes_map_to_a_shared_vocabulary(self):
        # Without this every insurer's private code becomes its own category and
        # the rejection report is a list of one-offs nobody can act on.
        assert canonical_reason("NOT_ELIGIBLE") == "MEMBER_INELIGIBLE"
        assert canonical_reason("MEMBER_INELIGIBLE") == "MEMBER_INELIGIBLE"

    def test_different_insurers_wording_collapses_to_one_reason(self):
        assert canonical_reason("NON_FORMULARY") == canonical_reason("ITEM_NOT_COVERED")

    def test_an_unknown_code_survives_as_itself(self):
        """Not bucketed as OTHER.

        A new insurer code must show up as itself so somebody maps it
        deliberately, rather than disappearing into a catch-all.
        """
        assert canonical_reason("SOME_NEW_INSURER_CODE") == "SOME_NEW_INSURER_CODE"

    def test_a_blank_code_is_explicit(self):
        assert canonical_reason("") == "UNSPECIFIED"
        assert canonical_reason(None) == "UNSPECIFIED"

    def test_matching_is_case_insensitive(self):
        assert canonical_reason("not_eligible") == "MEMBER_INELIGIBLE"

    def test_every_mapped_value_is_a_canonical_name(self):
        # The right-hand side must not itself need mapping.
        for canonical in CANONICAL_REJECTION_REASONS.values():
            assert canonical_reason(canonical) == canonical


class TestResubmissionEligibility:
    def test_a_correctable_rejection_is_resubmittable(self):
        assert "INVALID_CODE" in RESUBMITTABLE_REASONS
        assert "MISSING_ATTACHMENT" in RESUBMITTABLE_REASONS

    @pytest.mark.parametrize(
        "reason",
        ["MEMBER_INELIGIBLE", "COVERAGE_EXPIRED", "MEDICINE_NOT_COVERED", "PROVIDER_NOT_CONTRACTED"],
    )
    def test_an_uncorrectable_rejection_is_not(self, reason):
        """Resubmitting these unchanged just produces the same rejection.

        Something else has to change first -- a contract, a mapping, an
        eligibility record -- and pretending otherwise wastes a claims clerk's
        week.
        """
        assert reason not in RESUBMITTABLE_REASONS

    def test_a_duplicate_is_never_resubmittable(self):
        # Resubmitting a duplicate produces a third copy.
        assert "DUPLICATE_CLAIM" not in RESUBMITTABLE_REASONS


class TestRejectionRecording:
    def test_only_a_rejection_may_be_recorded_as_one(self):
        approved = AdapterResult(
            transport_state=TransportState.ACCEPTED, business_state=BusinessState.APPROVED
        )
        with pytest.raises(ValidationError):
            RejectionService.record(claim=None, result=approved)

    def test_a_pending_response_is_not_a_rejection(self):
        pending = AdapterResult(
            transport_state=TransportState.ACCEPTED, business_state=BusinessState.PENDING
        )
        with pytest.raises(ValidationError):
            RejectionService.record(claim=None, result=pending)


# ─── reversal ────────────────────────────────────────────────────────────────


class TestReversal:
    def test_a_reversal_requires_a_reason_and_an_actor(self, db):
        from django.core.exceptions import PermissionDenied

        with pytest.raises(ValidationError):
            ClaimReversalService.reverse(claim=None, actor=object(), reason="  ")
        with pytest.raises(PermissionDenied):
            ClaimReversalService.reverse(claim=None, actor=None, reason="Supply reversed")

    def test_money_already_received_remains_recoverable(self):
        """A reversal after payment does not cancel the payment.

        The insurer transferred funds. Getting them back is a separate act
        somebody has to perform, and it only happens if the amount is visible.
        """

        class Claim:
            paid_amount = cash("750.00")

        assert ClaimReversalService.recoverable_amount(claim=Claim()) == cash("750.00")

    def test_an_unpaid_reversal_recovers_nothing(self):
        class Claim:
            paid_amount = cash("0.00")

        assert ClaimReversalService.recoverable_amount(claim=Claim()) == cash("0.00")


def lifecycle_source() -> str:
    """The module's own text, located from the module rather than the cwd.

    A relative path here passes when pytest runs from backend/ and fails from
    the repository root, which turns a real assertion into a coin flip.
    """
    from apps.insurance.services import lifecycle

    return open(lifecycle.__file__).read()


class TestCorrectionsPreserveHistory:
    """The property the whole module exists for."""

    def test_reversal_does_not_touch_the_claimed_amount(self):
        source = lifecycle_source()
        reverse_block = source.split("def reverse(")[1].split("def is_reversed")[0]

        # The original claim keeps what it asked for and what was decided.
        # Only the forward-looking payable changes.
        assert "claimed_gross_amount" not in reverse_block
        assert "approved_amount" not in reverse_block
        assert "insurer_payable_amount" in reverse_block

    def test_resubmission_creates_a_new_claim_rather_than_editing(self):
        source = lifecycle_source()
        resubmit_block = source.split("def resubmit(")[1].split("def chain(")[0]

        # A new row, linked to the original.
        assert "PrescriptionClaim.all_objects.create" in resubmit_block
        assert "ClaimResubmission.all_objects.create" in resubmit_block

    def test_a_resubmission_reuses_the_same_supply(self):
        source = lifecycle_source()
        resubmit_block = source.split("def resubmit(")[1].split("def chain(")[0]
        # A resubmission re-states a claim for medicine already dispensed. It
        # must never look like a second supply.
        assert "supply=original.supply" in resubmit_block

    def test_reversal_is_not_deletion(self):
        source = lifecycle_source()
        # Nothing in this module deletes a claim.
        assert ".delete()" not in source


class TestMoney:
    def test_money_never_goes_through_float(self):
        assert money(0.1) == cash("0.10")

    def test_none_is_zero(self):
        assert money(None) == cash("0.00")
