"""Coverage, eligibility and preauthorisation.

Three properties, each corresponding to a way a pharmacy ends up out of pocket
or a patient ends up short of medicine:

* a membership number is not proof of cover;
* a stale eligibility answer is not an eligibility answer;
* a partial approval is a funding decision, not a clinical one, and must never
  silently reduce a prescription.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.insurance.adapters.base import AdapterResult, BusinessState, TransportState
from apps.insurance.adapters.fake import FakeInsurerAdapter, Scenario
from apps.insurance.services.coverage import (
    DEFAULT_VALIDITY,
    CoverageNotEligible,
    CoverageNotVerified,
    CoverageService,
    EligibilityStale,
)
from apps.insurance.services.preauthorisation import (
    PreauthorisationRequired,
    PreauthorisationService,
    money,
    quantity,
)


def cash(value: str) -> Decimal:
    return Decimal(value)


# ─── a card is not cover ─────────────────────────────────────────────────────


class TestLimits:
    def test_a_spent_limit_covers_nothing(self):
        class Coverage:
            remaining_limit = cash("0.00")

        assert CoverageService.within_limit(coverage=Coverage(), amount=cash("0.01")) is False

    def test_a_limit_covers_up_to_its_value(self):
        class Coverage:
            remaining_limit = cash("5000.00")

        assert CoverageService.within_limit(coverage=Coverage(), amount=cash("5000.00")) is True
        assert CoverageService.within_limit(coverage=Coverage(), amount=cash("5000.01")) is False


class TestMemberMatching:
    def test_a_blank_membership_number_matches_nothing(self, db):
        # Matching loosely here attaches one patient's dispensing history to
        # another person's insurance record.
        assert (
            CoverageService.match_member(tenant_id="t1", membership_number="   ", patient=None)
            is None
        )
        assert (
            CoverageService.match_member(tenant_id="t1", membership_number="", patient=None)
            is None
        )


# ─── stale eligibility ───────────────────────────────────────────────────────


class TestEligibilityValidity:
    def test_the_validity_window_is_short(self):
        # The facts behind an eligibility answer change without anybody telling
        # the pharmacy.
        assert DEFAULT_VALIDITY <= timedelta(hours=8)

    def test_an_unreachable_insurer_is_not_a_yes(self):
        """An absence of an answer is not a refusal, and certainly not consent."""

        class UnreachableAdapter:
            def verify_coverage(self, *, request):
                return AdapterResult(
                    transport_state=TransportState.TIMEOUT,
                    business_state=BusinessState.UNKNOWN,
                )

        from apps.insurance.services.coverage import EligibilityService

        class Member:
            membership_number = "MEM-1"

        class Patient:
            pk = "pat-1"

        class Insurer:
            code = "FAKE"

        with pytest.raises(CoverageNotVerified):
            EligibilityService.verify(
                tenant_id="t1",
                insurer=Insurer(),
                member=Member(),
                patient=Patient(),
                adapter=UnreachableAdapter(),
            )

    def test_the_three_refusals_are_distinct(self):
        # They need three different responses at the counter: re-verify, tell
        # the patient, or take cash.
        assert CoverageNotVerified is not CoverageNotEligible
        assert EligibilityStale is not CoverageNotEligible
        for exception in (CoverageNotVerified, CoverageNotEligible, EligibilityStale):
            assert issubclass(exception, ValidationError)


# ─── preauthorisation ────────────────────────────────────────────────────────


class TestPreauthRequirement:
    def test_a_controlled_medicine_always_needs_authorisation(self):
        # Guessing "no" commits the provider to money it may not recover.
        assert (
            PreauthorisationService.is_required(insurer=object(), controlled=True) is True
        )

    def test_a_threshold_is_inclusive(self):
        class Scheme:
            preauth_threshold_amount = cash("5000.00")

        assert (
            PreauthorisationService.is_required(
                insurer=object(), scheme=Scheme(), amount=cash("5000.00")
            )
            is True
        )
        assert (
            PreauthorisationService.is_required(
                insurer=object(), scheme=Scheme(), amount=cash("4999.99")
            )
            is False
        )


class TestIdempotency:
    def test_the_key_is_stable(self):
        class Preauth:
            tenant_id = "t1"
            pk = "p1"

        # Two authorisation numbers for one prescription leaves a pharmacy
        # unable to tell which the insurer will honour.
        first = PreauthorisationService.build_idempotency_key(preauth=Preauth())
        second = PreauthorisationService.build_idempotency_key(preauth=Preauth())
        assert first == second


class TestPartialApproval:
    """The central property: a funding decision never rewrites a prescription."""

    def test_the_fake_insurer_halves_the_quantity(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.PARTIAL_APPROVAL)
        result = adapter.submit_preauthorisation(
            request={"lines": [{"line_reference": "l1", "quantity": "60", "amount": "1200.00"}]}
        )
        assert result.business_state == BusinessState.PARTIALLY_APPROVED
        assert result.lines[0].approved_quantity == Decimal("30")

    def test_partial_approval_is_not_reported_as_approval(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.PARTIAL_APPROVAL)
        result = adapter.submit_preauthorisation(request={"lines": []})
        assert result.business_state != BusinessState.APPROVED

    def test_a_rejected_preauthorisation_authorises_nothing(self):
        adapter = FakeInsurerAdapter(scenario=Scenario.PREAUTH_REJECTED)
        result = adapter.submit_preauthorisation(request={"lines": []})
        assert result.business_state == BusinessState.REJECTED
        assert result.establishes_liability is False


class TestPreauthValidity:
    def _preauth(self, status, valid_from=None, valid_to=None):
        from apps.insurance.models import PrescriptionPreauthorisation

        class Preauth:
            pass

        preauth = Preauth()
        preauth.status = status
        preauth.valid_from = valid_from
        preauth.valid_to = valid_to
        preauth.preauth_number = "PA-1"
        preauth.Status = PrescriptionPreauthorisation.Status
        return preauth

    def test_an_approved_authorisation_is_valid(self):
        from apps.insurance.models import PrescriptionPreauthorisation

        preauth = self._preauth(PrescriptionPreauthorisation.Status.APPROVED)
        assert PreauthorisationService.is_valid_for_supply(preauth=preauth) is True

    def test_a_partial_approval_still_funds_its_approved_portion(self):
        from apps.insurance.models import PrescriptionPreauthorisation

        preauth = self._preauth(PrescriptionPreauthorisation.Status.PARTIALLY_APPROVED)
        assert PreauthorisationService.is_valid_for_supply(preauth=preauth) is True

    @pytest.mark.parametrize(
        "status", ["DRAFT", "PENDING", "REJECTED", "EXPIRED", "CANCELLED", "MORE_INFO_REQUIRED"]
    )
    def test_no_other_status_funds_a_supply(self, status):
        preauth = self._preauth(status)
        assert PreauthorisationService.is_valid_for_supply(preauth=preauth) is False

    def test_an_expired_authorisation_is_refused(self):
        from datetime import date

        from apps.insurance.models import PrescriptionPreauthorisation

        preauth = self._preauth(
            PrescriptionPreauthorisation.Status.APPROVED,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 1, 31),
        )
        # Insurers refuse claims against expired authorisations routinely, and
        # the provider carries the cost.
        assert (
            PreauthorisationService.is_valid_for_supply(preauth=preauth, on_date=date(2026, 7, 26))
            is False
        )

    def test_an_authorisation_is_not_valid_before_it_starts(self):
        from datetime import date

        from apps.insurance.models import PrescriptionPreauthorisation

        preauth = self._preauth(
            PrescriptionPreauthorisation.Status.APPROVED,
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 8, 31),
        )
        assert (
            PreauthorisationService.is_valid_for_supply(preauth=preauth, on_date=date(2026, 7, 26))
            is False
        )

    def test_a_missing_authorisation_is_refused_explicitly(self):
        with pytest.raises(PreauthorisationRequired, match="none exists"):
            PreauthorisationService.require_valid(preauth=None)


class TestArithmetic:
    def test_money_never_goes_through_float(self):
        assert money(0.1) == cash("0.10")

    def test_quantity_keeps_precision(self):
        # Quantities are not money and must not be quantised to two places;
        # a 0.5 mL dose is real.
        assert quantity("0.5000") == Decimal("0.5000")

    def test_none_is_zero(self):
        assert money(None) == cash("0.00")
        assert quantity(None) == Decimal("0.00")


class TestManualVerification:
    def test_a_manual_verification_demands_reason_evidence_and_actor(self, db):
        from apps.insurance.services.coverage import EligibilityService

        # A manual verification carries the provider's risk, not the insurer's,
        # so whoever accepted that risk must be identifiable.
        with pytest.raises(ValidationError):
            EligibilityService.record_manual_verification(
                tenant_id="t1", insurer=None, member=None, patient=None,
                actor=object(), reason="", evidence="call-ref-1",
            )
        with pytest.raises(ValidationError):
            EligibilityService.record_manual_verification(
                tenant_id="t1", insurer=None, member=None, patient=None,
                actor=object(), reason="Insurer portal down", evidence="",
            )
        with pytest.raises(PermissionDenied):
            EligibilityService.record_manual_verification(
                tenant_id="t1", insurer=None, member=None, patient=None,
                actor=None, reason="Insurer portal down", evidence="call-ref-1",
            )
