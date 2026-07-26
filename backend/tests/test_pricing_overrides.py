"""Manual price override governance.

A cashier must not be able to type a new price. These tests guard the exception
to that rule, which has to exist -- damaged boxes, price matches, goodwill on a
complaint -- without becoming an unbounded discount button.

Every relaxation here has a cost measured in margin, so do not loosen a floor or
a threshold to make a workflow smoother.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.pricing.overrides import (
    APPROVE_CAPABILITY,
    BELOW_FLOOR_CAPABILITY,
    REQUEST_CAPABILITY,
    OverridePolicy,
    PriceOverrideService,
    money,
)


def cash(value: str) -> Decimal:
    return Decimal(value)


class Actor:
    """Stands in for a user holding a set of capabilities."""

    def __init__(self, pk, *capabilities):
        self.pk = pk
        self._capabilities = set(capabilities)
        self.is_platform_admin = False
        self.is_superuser = False

    def has_capability(self, capability, tenant_id=None):
        return capability in self._capabilities


POLICY = OverridePolicy(
    minimum_allowed_price=cash("900.00"),
    maximum_discount_percentage=cash("10"),
    maximum_absolute_discount=cash("150.00"),
)


# ─── assessment ──────────────────────────────────────────────────────────────


class TestAssessment:
    def test_a_small_discount_needs_no_approval(self):
        assessment = PriceOverrideService.assess(
            resolved_price=cash("1000.00"), override_price=cash("950.00"), policy=POLICY
        )
        assert assessment.requires_approval is False
        assert assessment.discount_amount == cash("50.00")
        assert assessment.discount_percentage == cash("5.00")

    def test_a_discount_beyond_the_percentage_needs_approval(self):
        assessment = PriceOverrideService.assess(
            resolved_price=cash("1000.00"), override_price=cash("880.00"), policy=POLICY
        )
        assert assessment.requires_approval is True
        assert any("exceeds" in reason for reason in assessment.reasons)

    def test_a_discount_beyond_the_absolute_cap_needs_approval(self):
        # 12% of 2000 is 240: within the percentage on a large line, but past
        # the cash cap. Both bounds matter, and a percentage alone lets a big
        # line give away far more than a small one.
        policy = OverridePolicy(
            maximum_discount_percentage=cash("20"), maximum_absolute_discount=cash("150.00")
        )
        assessment = PriceOverrideService.assess(
            resolved_price=cash("2000.00"), override_price=cash("1760.00"), policy=policy
        )
        assert assessment.requires_approval is True

    def test_below_the_floor_needs_its_own_authority(self):
        assessment = PriceOverrideService.assess(
            resolved_price=cash("1000.00"), override_price=cash("850.00"), policy=POLICY
        )
        assert assessment.requires_below_floor_authority is True
        assert any("minimum allowed price" in reason for reason in assessment.reasons)

    def test_the_floor_is_measured_against_the_resolved_price(self):
        """A sequence of small reductions must not walk a price under the floor.

        Each assessment starts from the resolved price, so the fifth 5% is
        measured from 1000, not from what the fourth left behind.
        """
        first = PriceOverrideService.assess(
            resolved_price=cash("1000.00"), override_price=cash("950.00"), policy=POLICY
        )
        assert first.requires_below_floor_authority is False
        walked = PriceOverrideService.assess(
            resolved_price=cash("1000.00"), override_price=cash("890.00"), policy=POLICY
        )
        assert walked.requires_below_floor_authority is True

    def test_an_increase_requires_approval(self):
        # Overcharging is not the safe direction.
        assessment = PriceOverrideService.assess(
            resolved_price=cash("1000.00"), override_price=cash("1200.00"), policy=POLICY
        )
        assert assessment.requires_approval is True
        assert any("above the resolved price" in reason for reason in assessment.reasons)

    def test_a_negative_price_is_refused_outright(self):
        assessment = PriceOverrideService.assess(
            resolved_price=cash("1000.00"), override_price=cash("-10.00"), policy=POLICY
        )
        assert assessment.blocked is True

    def test_free_of_charge_is_permitted_but_needs_authority(self):
        # A zero price is a legitimate write-off, not an error -- but it is
        # below every floor, so it needs the authority for that.
        assessment = PriceOverrideService.assess(
            resolved_price=cash("1000.00"), override_price=cash("0.00"), policy=POLICY
        )
        assert assessment.permitted is True
        assert assessment.requires_below_floor_authority is True


# ─── who may ask ─────────────────────────────────────────────────────────────


class TestRequestAuthority:
    def test_a_cashier_without_the_capability_cannot_override(self, db):
        # The rule the module exists for.
        with pytest.raises(PermissionDenied, match="cannot type a new price"):
            PriceOverrideService.request(
                tenant=None, sku=None, branch=None, transaction_reference="TXN-1",
                resolved_price=cash("1000.00"), override_price=cash("950.00"),
                requested_by=Actor(1), reason_code="DAMAGED",
            )

    def test_a_reason_code_is_required(self, db):
        with pytest.raises(ValidationError, match="reason code"):
            PriceOverrideService.request(
                tenant=None, sku=None, branch=None, transaction_reference="TXN-1",
                resolved_price=cash("1000.00"), override_price=cash("950.00"),
                requested_by=Actor(1, REQUEST_CAPABILITY), reason_code="  ",
            )

    def test_an_override_must_name_its_transaction(self, db):
        """Without one it would change the price for everyone."""
        with pytest.raises(ValidationError, match="name the transaction"):
            PriceOverrideService.request(
                tenant=None, sku=None, branch=None, transaction_reference="",
                resolved_price=cash("1000.00"), override_price=cash("950.00"),
                requested_by=Actor(1, REQUEST_CAPABILITY), reason_code="DAMAGED",
            )


# ─── who may approve ─────────────────────────────────────────────────────────


class TestApprovalAuthority:
    def _pending(self):
        class Override:
            pk = "ovr-1"
            status = "REQUESTED"
            requested_by_id = 1
            resolved_price = cash("1000.00")
            # An increase: needs approval, but is not below the floor, so the
            # ordinary approval path is what gets exercised.
            override_price = cash("1200.00")
            approved_by = None
            approved_at = None

            def save(self, update_fields=None):
                pass

        from apps.pricing.models import ManualPriceOverride

        override = Override()
        override.Status = ManualPriceOverride.Status
        return override

    def test_the_requester_cannot_approve_their_own(self, db):
        """An override a cashier can approve for themselves is not a control."""
        override = self._pending()
        with pytest.raises(PermissionDenied, match="person who requested it"):
            PriceOverrideService.approve(
                override=override,
                approver=Actor(1, APPROVE_CAPABILITY),
                policy=POLICY,
            )

    def test_an_approver_without_the_capability_is_refused(self, db):
        override = self._pending()
        with pytest.raises(PermissionDenied, match="approve capability"):
            PriceOverrideService.approve(
                override=override, approver=Actor(2), policy=POLICY
            )

    def test_an_anonymous_approver_is_refused(self, db):
        override = self._pending()
        with pytest.raises(PermissionDenied, match="named approver"):
            PriceOverrideService.approve(override=override, approver=None, policy=POLICY)

    def test_a_supervisor_may_approve_within_the_floor(self, db):
        override = self._pending()
        approved = PriceOverrideService.approve(
            override=override, approver=Actor(2, APPROVE_CAPABILITY), policy=POLICY
        )
        assert approved.status == "APPROVED"

    def test_below_the_floor_needs_more_than_ordinary_approval(self, db):
        """A supervisor waving through a small discount is not the same decision
        as a manager selling below the minimum."""
        override = self._pending()
        override.override_price = cash("850.00")
        with pytest.raises(PermissionDenied, match="below_floor"):
            PriceOverrideService.approve(
                override=override, approver=Actor(2, APPROVE_CAPABILITY), policy=POLICY
            )

    def test_a_manager_with_floor_authority_may_approve_below_it(self, db):
        override = self._pending()
        override.override_price = cash("850.00")
        approved = PriceOverrideService.approve(
            override=override,
            approver=Actor(3, APPROVE_CAPABILITY, BELOW_FLOOR_CAPABILITY),
            policy=POLICY,
        )
        assert approved.status == "APPROVED"


# ─── capability separation ───────────────────────────────────────────────────


class TestCapabilitySeparation:
    def test_requesting_and_approving_are_distinct_capabilities(self):
        # Held by the same person, the pair is not a separation of duties.
        assert REQUEST_CAPABILITY != APPROVE_CAPABILITY

    def test_going_below_the_floor_is_its_own_capability(self):
        assert BELOW_FLOOR_CAPABILITY not in {REQUEST_CAPABILITY, APPROVE_CAPABILITY}

    def test_holding_request_does_not_confer_approve(self):
        actor = Actor(1, REQUEST_CAPABILITY)
        assert actor.has_capability(APPROVE_CAPABILITY) is False


# ─── cost stays out of the operator's view ───────────────────────────────────


class TestCostConfidentiality:
    def test_the_policy_carries_no_cost(self):
        """Confidential cost must not reach a POS operator.

        The floor is expressed as a price; the margin calculation that produced
        it stays in HQ. A screen that can show a cost-derived floor has
        published the cost.
        """
        fields = set(OverridePolicy.__dataclass_fields__)
        for leak in {"cost", "unit_cost", "landed_cost", "margin", "weighted_average_cost"}:
            assert leak not in fields

    def test_the_assessment_carries_no_cost(self):
        from apps.pricing.overrides import OverrideAssessment

        fields = set(OverrideAssessment.__dataclass_fields__)
        assert not any("cost" in name or "margin" in name for name in fields)


class TestArithmetic:
    def test_money_never_goes_through_float(self):
        assert money(0.1) == cash("0.10")

    def test_percentages_are_exact(self):
        assessment = PriceOverrideService.assess(
            resolved_price=cash("3.00"), override_price=cash("2.00"),
            policy=OverridePolicy(maximum_discount_percentage=cash("50")),
        )
        # A third, to the penny, without binary drift.
        assert assessment.discount_percentage == cash("33.33")
