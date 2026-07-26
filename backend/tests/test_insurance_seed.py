"""The insurance demo seed.

A seed that duplicates on a second run teaches people not to run it, and then
nobody exercises the thing it was written to exercise. So the central test here
runs it twice and counts rows.

The scenarios it creates are chosen to cover the states that are easy to get
wrong, not the ones that are common: a suspended member holding a valid card, a
coverage that lapsed before today, a verification that has already expired, a
remittance line naming no claim, and an insurer configured against an adapter
nobody has implemented.
"""
import pytest
from django.core.management import call_command

from apps.insurance.models import (
    CoverageVerification,
    InsuranceCoverage,
    InsuranceMember,
    InsuranceRemittance,
    InsuranceRemittanceLine,
    Insurer,
    InsurerPlan,
    InsurerScheme,
)

SEEDED_MODELS = [
    Insurer,
    InsurerScheme,
    InsurerPlan,
    InsuranceMember,
    InsuranceCoverage,
    CoverageVerification,
    InsuranceRemittance,
    InsuranceRemittanceLine,
]


def counts() -> dict[str, int]:
    return {model.__name__: model.all_objects.count() for model in SEEDED_MODELS}


@pytest.fixture
def seeded(db):
    call_command("seed_insurance_demo")
    return counts()


class TestIdempotence:
    def test_running_twice_creates_nothing_new(self, seeded):
        """The property the whole command depends on."""
        call_command("seed_insurance_demo")
        assert counts() == seeded

    def test_running_three_times_is_still_stable(self, seeded):
        call_command("seed_insurance_demo")
        call_command("seed_insurance_demo")
        assert counts() == seeded

    def test_the_seed_actually_creates_something(self, seeded):
        # A seed that creates nothing would pass every idempotence test.
        assert seeded["Insurer"] >= 2
        assert seeded["InsuranceMember"] >= 4
        assert seeded["InsuranceCoverage"] >= 4


class TestScenarioCoverage:
    """Each scenario corresponds to a way the naive implementation is wrong."""

    def test_an_active_coverage_exists(self, seeded):
        assert InsuranceCoverage.all_objects.filter(
            status=InsuranceCoverage.Status.ACTIVE
        ).exists()

    def test_a_suspended_coverage_exists(self, seeded):
        # A real card whose cover is not real. Proves that "the number exists"
        # is not the same question as "will they pay".
        assert InsuranceCoverage.all_objects.filter(
            status=InsuranceCoverage.Status.SUSPENDED
        ).exists()

    def test_a_lapsed_coverage_exists(self, seeded):
        from django.utils import timezone

        # Something for a service-date filter to actually exclude.
        assert InsuranceCoverage.all_objects.filter(
            valid_to__lt=timezone.now().date()
        ).exists()

    def test_a_coverage_with_copay_and_coinsurance_exists(self, seeded):
        from decimal import Decimal

        coverage = InsuranceCoverage.all_objects.filter(
            copay_amount__gt=Decimal("0.00")
        ).first()
        assert coverage is not None
        assert coverage.coinsurance_percentage > Decimal("0.00")

    def test_an_expired_verification_exists(self, seeded):
        from django.utils import timezone

        # Without this the staleness check passes because nothing is ever old.
        assert CoverageVerification.all_objects.filter(
            expires_at__lt=timezone.now()
        ).exists()

    def test_a_current_verification_also_exists(self, seeded):
        from django.utils import timezone

        assert CoverageVerification.all_objects.filter(
            expires_at__gt=timezone.now()
        ).exists()

    def test_an_unmatched_remittance_line_exists(self, seeded):
        """Money that arrived and cannot be placed.

        The case a happy-path seed never produces, and the one somebody has to
        investigate.
        """
        line = InsuranceRemittanceLine.all_objects.filter(claim__isnull=True).first()
        assert line is not None
        assert line.status == "UNMATCHED"


class TestSeededAdapterHonesty:
    def test_sha_is_configured_but_has_no_registered_adapter(self, seeded):
        """The configuration exists; the integration does not.

        A configured insurer whose adapter is unregistered must fail loudly at
        submission rather than appear to work, and the seed should make that
        state reachable so somebody meets it in development instead of in
        production.
        """
        from apps.insurance.adapters.base import ADAPTERS

        sha = Insurer.all_objects.filter(
            integration_adapter=Insurer.IntegrationAdapter.SHA
        ).first()
        assert sha is not None
        assert "SHA" not in ADAPTERS

    def test_the_private_insurer_uses_the_fake_adapter(self, seeded):
        from apps.insurance.adapters.base import ADAPTERS

        private = Insurer.all_objects.filter(
            integration_adapter=Insurer.IntegrationAdapter.FAKE
        ).first()
        assert private is not None
        assert "FAKE" in ADAPTERS

    def test_everything_seeded_is_sandbox(self, seeded):
        # Demonstration data must never be configured against production.
        for insurer in Insurer.all_objects.all():
            assert insurer.environment == Insurer.Environment.SANDBOX


class TestSeedSafety:
    def test_the_seed_fabricates_no_insurer_decision(self):
        """No adjudication, approval or payment is invented.

        Seeded data that carries an approval nobody granted trains people to
        believe approvals appear on their own.
        """
        from apps.insurance.management.commands import seed_insurance_demo as mod

        source = open(mod.__file__).read()
        for forbidden in [
            "ClaimAdjudication",
            "InsurancePaymentAllocation",
            "adjudication_state",
            "approved_amount",
        ]:
            assert forbidden not in source

    def test_seeded_rows_are_identifiable(self):
        from apps.insurance.management.commands import seed_insurance_demo as mod

        # So a cleanup can find them, and so nobody mistakes them for real.
        assert mod.DEMO_PREFIX
