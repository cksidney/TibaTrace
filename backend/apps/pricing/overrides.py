"""Manual price overrides, and the floors that bound them.

A cashier must not be able to type a new price. That is the whole rule, and
everything here exists to make the exception to it controlled rather than
absent -- because the exceptions are real: a damaged box, a price match, a
goodwill gesture on a complaint.

Three things bound an override.

**A floor.** Below the minimum selling price the answer is no, whoever is
asking. Above it but below the supervisor threshold, a supervisor may authorise.
The floor is checked against the resolved price, not against the last override,
so a sequence of small reductions cannot walk a price down past it.

**An approver who is not the requester.** An override a cashier can approve for
themselves is not a control. The requester and approver are recorded
separately, and they must differ.

**A scope of exactly one transaction.** An override is a decision about a
particular sale. Letting it touch the master price turns one person's judgement
into everybody's price, silently and permanently.

Cost is deliberately absent from what an operator sees. §17 is explicit that
confidential cost data must not be exposed to ordinary POS operators, so the
floor is expressed as a price, and the margin calculation that produced it stays
in HQ.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ManualPriceOverride

ZERO = Decimal("0.00")
PENNY = Decimal("0.01")
HUNDRED = Decimal("100")

#: Capabilities. Requesting an override and approving one are separate powers,
#: because the whole point is that they are held by different people.
REQUEST_CAPABILITY = "pricing.manual_override.request"
APPROVE_CAPABILITY = "pricing.manual_override.approve"
#: Going below the floor at all. Deliberately distinct from ordinary approval:
#: a supervisor authorising a small discount is not the same decision as a
#: manager selling below the minimum.
BELOW_FLOOR_CAPABILITY = "pricing.manual_override.approve_below_floor"


def money(value) -> Decimal:
    if value is None:
        return ZERO
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


def _holds(actor, capability: str) -> bool:
    if actor is None:
        return False
    if getattr(actor, "is_platform_admin", False) or getattr(actor, "is_superuser", False):
        return True
    checker = getattr(actor, "has_capability", None)
    return bool(callable(checker) and checker(capability))


@dataclass(frozen=True)
class OverridePolicy:
    """The bounds a tenant places on manual pricing.

    Expressed as prices and percentages, never as costs. An operator screen that
    can display a floor derived from cost has published the cost.
    """

    #: Absolute floor. Nothing sells below this without BELOW_FLOOR_CAPABILITY.
    minimum_allowed_price: Decimal | None = None
    #: Largest reduction an ordinary approver may authorise.
    maximum_discount_percentage: Decimal = Decimal("10")
    maximum_absolute_discount: Decimal | None = None
    #: Whether an increase above the resolved price needs approving too. It
    #: does by default: overcharging a customer is not the safe direction.
    approve_increases: bool = True


@dataclass(frozen=True)
class OverrideAssessment:
    """What this override would need, and whether it is permitted at all."""

    permitted: bool
    requires_approval: bool
    requires_below_floor_authority: bool
    discount_amount: Decimal
    discount_percentage: Decimal
    reasons: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return not self.permitted


class PriceOverrideService:
    """Assesses, records and approves manual price overrides."""

    @staticmethod
    def assess(*, resolved_price, override_price, policy: OverridePolicy) -> OverrideAssessment:
        """Decide what this override needs, without applying it.

        Separate from recording it so a till can show the operator what will
        happen -- "this needs a supervisor" -- before they commit to asking.
        """
        resolved = money(resolved_price)
        proposed = money(override_price)
        reasons: list[str] = []

        if proposed < ZERO:
            return OverrideAssessment(
                permitted=False,
                requires_approval=True,
                requires_below_floor_authority=False,
                discount_amount=ZERO,
                discount_percentage=ZERO,
                reasons=("A price cannot be negative.",),
            )

        discount = resolved - proposed
        percentage = (
            (discount / resolved * HUNDRED).quantize(PENNY, rounding=ROUND_HALF_UP)
            if resolved > ZERO
            else ZERO
        )

        below_floor = (
            policy.minimum_allowed_price is not None
            and proposed < money(policy.minimum_allowed_price)
        )
        if below_floor:
            reasons.append(
                f"{proposed} is below the minimum allowed price of "
                f"{money(policy.minimum_allowed_price)}."
            )

        requires_approval = False
        if discount > ZERO:
            if percentage > money(policy.maximum_discount_percentage):
                requires_approval = True
                reasons.append(
                    f"A {percentage}% reduction exceeds the "
                    f"{money(policy.maximum_discount_percentage)}% an operator may apply."
                )
            if (
                policy.maximum_absolute_discount is not None
                and discount > money(policy.maximum_absolute_discount)
            ):
                requires_approval = True
                reasons.append(
                    f"A reduction of {discount} exceeds the "
                    f"{money(policy.maximum_absolute_discount)} an operator may apply."
                )
        elif discount < ZERO and policy.approve_increases:
            # Charging more than the resolved price is not the safe direction.
            requires_approval = True
            reasons.append(
                f"{proposed} is above the resolved price of {resolved}; "
                "an increase requires approval."
            )

        return OverrideAssessment(
            # Below the floor is still permitted, but only to someone holding
            # the authority for it. Refusing outright would leave a genuine
            # write-off with nowhere to go.
            permitted=True,
            requires_approval=requires_approval or below_floor,
            requires_below_floor_authority=below_floor,
            discount_amount=discount,
            discount_percentage=percentage,
            reasons=tuple(reasons),
        )

    @classmethod
    @transaction.atomic
    def request(cls, *, tenant, sku, branch, transaction_reference: str,
                resolved_price, override_price, requested_by, reason_code: str,
                reason: str = "", policy: OverridePolicy | None = None,
                expires_in_minutes: int = 60) -> ManualPriceOverride:
        """Raise an override request, scoped to one transaction.

        Requires the request capability and a reason code. "Manager said so" on
        a spreadsheet months later is not a reason anybody can audit, so the
        code is mandatory and the free-text sits alongside it.
        """
        policy = policy or OverridePolicy()

        if not _holds(requested_by, REQUEST_CAPABILITY):
            raise PermissionDenied(
                "A price override requires the pricing.manual_override.request "
                "capability. A cashier cannot type a new price."
            )
        if not str(reason_code or "").strip():
            raise ValidationError("A price override requires a reason code.")
        if not str(transaction_reference or "").strip():
            raise ValidationError(
                "A price override must name the transaction it applies to. An "
                "override with no transaction would change the price for everyone."
            )

        assessment = cls.assess(
            resolved_price=resolved_price, override_price=override_price, policy=policy
        )
        if assessment.blocked:
            raise ValidationError({"override": list(assessment.reasons)})

        return ManualPriceOverride.all_objects.create(
            tenant=tenant,
            sku=sku,
            branch=branch,
            transaction_reference=transaction_reference,
            resolved_price=money(resolved_price),
            override_price=money(override_price),
            reason_code=reason_code,
            reason=reason,
            requested_by=requested_by,
            status=(
                ManualPriceOverride.Status.REQUESTED
                if assessment.requires_approval
                else ManualPriceOverride.Status.APPROVED
            ),
            approved_at=None if assessment.requires_approval else timezone.now(),
            # Short-lived. An override authorised for a damaged box this morning
            # must not still be reducing prices tomorrow.
            expires_at=timezone.now() + timedelta(minutes=expires_in_minutes),
        )

    @classmethod
    @transaction.atomic
    def approve(cls, *, override: ManualPriceOverride, approver,
                policy: OverridePolicy | None = None) -> ManualPriceOverride:
        """Authorise a requested override.

        The requester may not approve their own, and going below the floor needs
        its own authority -- a supervisor waving through a small discount is not
        the same decision as a manager selling below the minimum.
        """
        policy = policy or OverridePolicy()

        if override.status != ManualPriceOverride.Status.REQUESTED:
            raise ValidationError(
                f"Only a requested override may be approved; this one is {override.status}."
            )
        if approver is None:
            raise PermissionDenied("A price override requires a named approver.")
        if override.requested_by_id == getattr(approver, "pk", None):
            raise PermissionDenied(
                "A price override cannot be approved by the person who requested it."
            )
        if not _holds(approver, APPROVE_CAPABILITY):
            raise PermissionDenied(
                "Approving a price override requires the "
                "pricing.manual_override.approve capability."
            )

        assessment = cls.assess(
            resolved_price=override.resolved_price,
            override_price=override.override_price,
            policy=policy,
        )
        if assessment.requires_below_floor_authority and not _holds(
            approver, BELOW_FLOOR_CAPABILITY
        ):
            raise PermissionDenied(
                "This price is below the minimum allowed price and requires the "
                "pricing.manual_override.approve_below_floor capability."
            )

        override.status = ManualPriceOverride.Status.APPROVED
        override.approved_by = approver
        override.approved_at = timezone.now()
        override.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        return override

    @staticmethod
    @transaction.atomic
    def reject(*, override: ManualPriceOverride, approver, reason: str = "") -> ManualPriceOverride:
        if override.status != ManualPriceOverride.Status.REQUESTED:
            raise ValidationError(
                f"Only a requested override may be rejected; this one is {override.status}."
            )
        if approver is None:
            raise PermissionDenied("A price override requires a named approver.")
        if override.requested_by_id == getattr(approver, "pk", None):
            raise PermissionDenied(
                "A price override cannot be rejected by the person who requested it."
            )
        if not _holds(approver, APPROVE_CAPABILITY):
            raise PermissionDenied(
                "Rejecting a price override requires the "
                "pricing.manual_override.approve capability."
            )
        override.status = ManualPriceOverride.Status.REJECTED
        override.approved_by = approver
        override.approved_at = timezone.now()
        if reason:
            override.reason = f"{override.reason}\nRejected: {reason}".strip()
        override.save(
            update_fields=["status", "approved_by", "approved_at", "reason", "updated_at"]
        )
        return override
