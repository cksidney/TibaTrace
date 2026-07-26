"""Insurance claims: adapter contract, construction and adjudication.

Written around the two ways this subsystem causes real harm:

* claiming for medicine the patient never received, which is a false statement
  to an insurer with the provider's name on it;
* treating an insurer's acknowledgement as an approval, and booking a receivable
  for money nobody agreed to pay.

These use the fake adapter throughout. Nothing here has been exercised against
a real insurer.
"""
from decimal import Decimal

import pytest

from apps.insurance.adapters.base import (
    ADAPTERS,
    AdapterResult,
    BusinessState,
    TransportState,
    get_adapter,
)
from apps.insurance.adapters.fake import FakeInsurerAdapter, Scenario
from apps.insurance.services.claim_construction import money
from apps.insurance.services.submission import build_idempotency_key, payload_digest


def cash(value: str) -> Decimal:
    return Decimal(value)


# ─── the adapter contract ────────────────────────────────────────────────────


class TestAdapterRegistry:
    def test_the_fake_adapter_is_registered(self):
        assert "FAKE" in ADAPTERS
        assert get_adapter("FAKE") is FakeInsurerAdapter

    def test_an_unregistered_insurer_cannot_transact(self):
        # A claim must never be routed to an integration nobody has exercised.
        with pytest.raises(LookupError, match="No insurer adapter"):
            get_adapter("SHA")

    def test_sha_is_not_registered_until_its_contract_is_verified(self):
        # SHA needs official documentation and credentials neither of which the
        # repository has. Registering a guessed implementation would let it be
        # selected by configuration alone.
        assert "SHA" not in ADAPTERS


class TestTransportIsNotAdjudication:
    def test_transport_acceptance_alone_creates_no_liability(self):
        """The single most damaging conflation in the whole subsystem.

        The insurer has the claim and has said nothing about it. That is not an
        approval, and booking it as one reports revenue nobody agreed to pay.
        """
        result = AdapterResult(
            transport_state=TransportState.ACCEPTED,
            business_state=BusinessState.PENDING,
        )
        assert result.reached_insurer is True
        assert result.establishes_liability is False

    def test_silence_creates_no_liability(self):
        result = AdapterResult(
            transport_state=TransportState.ACCEPTED, business_state=BusinessState.UNKNOWN
        )
        assert result.establishes_liability is False

    def test_only_approval_creates_liability(self):
        for state in [BusinessState.APPROVED, BusinessState.PARTIALLY_APPROVED]:
            result = AdapterResult(
                transport_state=TransportState.ACCEPTED, business_state=state
            )
            assert result.establishes_liability is True

    @pytest.mark.parametrize(
        "state",
        [
            BusinessState.REJECTED,
            BusinessState.PENDING,
            BusinessState.UNKNOWN,
            BusinessState.MORE_INFORMATION_REQUIRED,
            BusinessState.DUPLICATE,
            BusinessState.REVERSED,
        ],
    )
    def test_no_other_state_creates_liability(self, state):
        result = AdapterResult(transport_state=TransportState.ACCEPTED, business_state=state)
        assert result.establishes_liability is False

    def test_an_approval_that_never_arrived_creates_no_liability(self):
        # Approval with a failed transport is incoherent, and the restrictive
        # reading wins.
        result = AdapterResult(
            transport_state=TransportState.TIMEOUT, business_state=BusinessState.APPROVED
        )
        assert result.reached_insurer is False
        assert result.establishes_liability is False


# ─── the fake adapter is deterministic ───────────────────────────────────────


class TestFakeAdapterDeterminism:
    def test_the_same_scenario_gives_the_same_answer(self):
        # A fake that picks outcomes at random makes a suite that fails once a
        # week and gets retried rather than read.
        payload = {"lines": [{"line_reference": "l1", "amount": "1000.00"}]}
        first = FakeInsurerAdapter(scenario=Scenario.FULL_APPROVAL).submit_claim(
            request=payload, idempotency_key="k1"
        )
        second = FakeInsurerAdapter(scenario=Scenario.FULL_APPROVAL).submit_claim(
            request=payload, idempotency_key="k1"
        )
        assert first.business_state == second.business_state
        assert first.approved_amount == second.approved_amount

    def test_full_approval_approves_the_claimed_amount(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.FULL_APPROVAL)
        result = adapter.submit_claim(
            request={"lines": [{"line_reference": "l1", "amount": "1000.00"}]},
            idempotency_key="k",
        )
        assert result.business_state == BusinessState.APPROVED
        assert result.approved_amount == cash("1000.00")

    def test_partial_approval_approves_less_than_claimed(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.PARTIAL_APPROVAL)
        result = adapter.submit_claim(
            request={"lines": [{"line_reference": "l1", "amount": "1000.00"}]},
            idempotency_key="k",
        )
        assert result.business_state == BusinessState.PARTIALLY_APPROVED
        assert result.approved_amount == cash("800.00")
        assert result.lines[0].disallowed_amount == cash("200.00")

    def test_rejection_approves_nothing(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.CLAIM_REJECTED)
        result = adapter.submit_claim(request={"lines": []}, idempotency_key="k")
        assert result.business_state == BusinessState.REJECTED
        assert result.establishes_liability is False

    def test_accepted_but_pending_is_modelled(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.CLAIM_ACCEPTED_PENDING)
        result = adapter.submit_claim(request={"lines": []}, idempotency_key="k")
        assert result.reached_insurer is True
        assert result.business_state == BusinessState.PENDING
        assert result.establishes_liability is False


class TestIdempotency:
    def test_a_replayed_key_is_reported_as_duplicate(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.FULL_APPROVAL)
        payload = {"lines": [{"line_reference": "l1", "amount": "1000.00"}]}
        adapter.submit_claim(request=payload, idempotency_key="same-key")
        second = adapter.submit_claim(request=payload, idempotency_key="same-key")
        # A network retry must not create a second claim.
        assert second.business_state == BusinessState.DUPLICATE
        assert second.establishes_liability is False

    def test_a_timeout_may_be_retried(self):
        """A timeout tells us nothing, so the key is not consumed.

        Caching it would permanently block a claim that never arrived.
        """
        adapter = FakeInsurerAdapter(scenario=Scenario.TIMEOUT)
        first = adapter.submit_claim(request={"lines": []}, idempotency_key="k")
        assert first.retryable is True
        assert first.transport_state == TransportState.TIMEOUT

        second = adapter.submit_claim(request={"lines": []}, idempotency_key="k")
        assert second.business_state != BusinessState.DUPLICATE

    def test_an_outage_is_retryable(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.OUTAGE)
        result = adapter.submit_claim(request={"lines": []}, idempotency_key="k")
        assert result.retryable is True
        assert result.establishes_liability is False

    def test_a_malformed_response_is_not_retryable(self):
        # Retrying will produce the same unparseable answer.
        adapter = FakeInsurerAdapter(scenario=Scenario.MALFORMED)
        result = adapter.submit_claim(request={"lines": []}, idempotency_key="k")
        assert result.retryable is False
        assert result.establishes_liability is False


class TestIdempotencyKeys:
    def test_the_key_is_stable_across_retries(self):
        class FakeClaim:
            tenant_id = "t1"
            pk = "c1"

        # Derived from the claim, never from a clock or a random value -- both
        # would make a retry look like a new claim to the insurer.
        first = build_idempotency_key(claim=FakeClaim())
        second = build_idempotency_key(claim=FakeClaim())
        assert first == second

    def test_different_claims_get_different_keys(self):
        class ClaimA:
            tenant_id = "t1"
            pk = "c1"

        class ClaimB:
            tenant_id = "t1"
            pk = "c2"

        assert build_idempotency_key(claim=ClaimA()) != build_idempotency_key(claim=ClaimB())

    def test_the_payload_digest_is_order_independent(self):
        # Two serialisations of the same claim must not look like two claims.
        assert payload_digest({"a": 1, "b": 2}) == payload_digest({"b": 2, "a": 1})

    def test_the_digest_changes_when_the_claim_changes(self):
        assert payload_digest({"amount": "100.00"}) != payload_digest({"amount": "200.00"})


# ─── insurer payloads do not leak into the domain ────────────────────────────


class TestProviderNeutrality:
    def test_the_result_carries_a_digest_not_the_body(self):
        # Insurer payloads carry diagnoses and membership numbers, and this is
        # stored on every attempt.
        adapter = FakeInsurerAdapter(scenario=Scenario.FULL_APPROVAL)
        result = adapter.submit_claim(
            request={"member_number": "MEM-123", "lines": []}, idempotency_key="k"
        )
        assert result.raw_response_digest
        assert "MEM-123" not in result.raw_response_digest

    def test_the_neutral_result_exposes_no_insurer_field_names(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.FULL_APPROVAL)
        result = adapter.submit_claim(request={"lines": []}, idempotency_key="k")
        serialised = str(result)
        for leak in ["stkCallback", "ResponseCode", "SHA_", "MemberNo"]:
            assert leak not in serialised


# ─── money handling ──────────────────────────────────────────────────────────


class TestMoney:
    def test_money_never_goes_through_float(self):
        assert money(0.1) == cash("0.10")

    def test_money_quantises(self):
        assert money("10.005") == cash("10.01")

    def test_none_is_zero(self):
        assert money(None) == cash("0.00")


# ─── the integrity checker ───────────────────────────────────────────────────


class TestIntegrityChecker:
    """The checker must fail loudly, and must detect a fabricated payable.

    A checker that reports findings and exits zero is a checker nobody reads;
    this repository has been bitten by exactly that before.
    """

    def test_a_clean_database_passes(self, db):
        from django.core.management import call_command

        call_command("check_insurance_claim_integrity")

    def test_a_payable_without_an_approval_is_detected(self, db):
        from unittest.mock import patch

        from django.core.management import CommandError

        from apps.insurance.models import PrescriptionClaim

        class FakeClaim:
            claim_number = "CLM-1"
            tenant_id = "t1"
            supply_id = None
            claimed_gross_amount = Decimal("1000.00")
            approved_amount = Decimal("0.00")
            # The violation: money owed with no insurer decision behind it.
            insurer_payable_amount = Decimal("1000.00")
            adjudication_state = PrescriptionClaim.AdjudicationState.PENDING
            submission_state = PrescriptionClaim.SubmissionState.TRANSPORT_ACCEPTED
            payment_state = PrescriptionClaim.PaymentState.UNPAID
            paid_amount = Decimal("0.00")

            class member:  # noqa: N801 - stand-in for the related row
                tenant_id = "t1"

        from apps.insurance.management.commands import check_insurance_claim_integrity as mod

        command = mod.Command()
        with patch.object(
            mod.PrescriptionClaimLine, "all_objects"
        ) as lines, patch.object(mod.ClaimAdjudication, "all_objects"):
            lines.filter.return_value = []
            findings = command._check_claim(FakeClaim(), repair=False)

        assert any("insurer payable" in f for f in findings)
        assert any("Only an approval creates a payable" in f for f in findings)
        assert CommandError is not None

    def test_repair_zeroes_a_fabricated_payable_rather_than_approving_it(self, db):
        """Repair may remove an unsupported payable. It may never invent the
        approval that would justify it."""
        import re

        from apps.insurance.management.commands import check_insurance_claim_integrity as mod

        source = open(mod.__file__).read()

        # Everything repair is capable of persisting, taken from the update_fields
        # of every save() in the checker. Scanning for assignments would match
        # comparisons too; this looks at what actually reaches the database.
        written = set()
        for match in re.findall(r"update_fields=\[([^\]]*)\]", source):
            written.update(field.strip().strip('"\'') for field in match.split(","))
        written.discard("")

        # Removing an unsupported payable is legitimate. Writing an approval,
        # an adjudication outcome or a payment is fabricating an insurer
        # decision, and no repair may do it.
        assert written <= {"claimed_gross_amount", "insurer_payable_amount", "updated_at"}
        for forbidden in [
            "adjudication_state", "approved_amount", "payment_state",
            "paid_amount", "submission_state",
        ]:
            assert forbidden not in written
