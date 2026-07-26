"""Holding a price while the customer pays.

The question this answers: was the customer charged what they were quoted?

Between the quote and the money there is a window -- sometimes seconds,
sometimes a held basket resumed after lunch -- in which a scheduled price change
activates, a promotion ends, or somebody publishes a new version. Without a lock
the till silently charges the new figure, and the customer is standing there
holding a slip that says something else.

Two rules keep the lock honest.

**A lock is not a promise the price still exists.** It expires. A basket held
overnight and resumed does not get yesterday's promotion; it gets re-priced, and
the operator is told the price moved.

**A changed basket invalidates its own lock.** The locked price answered a
question about one quantity for one customer. Change either and the answer no
longer applies, so the lock is dropped rather than stretched to cover a
different sale.

When a price does move, the operator is shown both figures and must
acknowledge. Silently charging either one is the failure -- the new price
because it was not agreed, the old price because it is no longer real.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import PriceLock
from .resolution import PricingContext, money

#: How long a quoted price is held. Short enough that a price change is not
#: outrun for long, generous enough to cover a customer finding their card.
DEFAULT_LOCK_MINUTES = 15


class LockPolicy:
    """When a price stops floating.

    LOCK_AT_PAYMENT_INTENT is the recommended default: prices stay live while
    the operator is still building the basket -- so an item added after a rise
    is priced correctly -- and freeze the moment the customer commits to paying.
    """

    NO_LOCK = "NO_LOCK"
    LOCK_AT_ITEM_ADD = "LOCK_AT_ITEM_ADD"
    LOCK_AT_CHECKOUT = "LOCK_AT_CHECKOUT"
    LOCK_AT_PAYMENT_INTENT = "LOCK_AT_PAYMENT_INTENT"
    LOCK_FOR_DURATION = "LOCK_FOR_DURATION"


@dataclass(frozen=True)
class PriceChange:
    """A locked price and the current price disagreeing."""

    line_reference: str
    locked_price: Decimal
    current_price: Decimal
    reason: str

    @property
    def difference(self) -> Decimal:
        return money(self.current_price) - money(self.locked_price)

    @property
    def customer_pays_more(self) -> bool:
        return self.difference > Decimal("0.00")

    def describe(self) -> str:
        direction = "increased" if self.customer_pays_more else "decreased"
        return (
            f"Line {self.line_reference} {direction} from {money(self.locked_price)} "
            f"to {money(self.current_price)}: {self.reason}"
        )


class PriceChangedAtCheckout(ValidationError):
    """The price moved between quote and payment.

    Carries both figures so the till can show them. Charging either without
    acknowledgement is wrong -- the new price was not agreed, and the old one is
    no longer real.
    """

    def __init__(self, changes: list[PriceChange]):
        self.changes = changes
        super().__init__([change.describe() for change in changes])


class PriceLockService:
    """Locks quoted prices and checks them at payment."""

    @staticmethod
    @transaction.atomic
    def lock(*, context: PricingContext, resolved, basket_reference: str,
             line_reference: str, minutes: int = DEFAULT_LOCK_MINUTES) -> PriceLock:
        """Hold this price for this line.

        Replaces any existing active lock for the line rather than adding a
        second. Two active locks on one line means two answers to what the
        customer owes.
        """
        PriceLock.all_objects.filter(
            tenant_id=context.tenant_id,
            basket_reference=basket_reference,
            line_reference=line_reference,
            status=PriceLock.Status.ACTIVE,
        ).update(
            status=PriceLock.Status.INVALIDATED,
            invalidation_reason="Superseded by a newer lock for the same line.",
            updated_at=timezone.now(),
        )

        return PriceLock.all_objects.create(
            tenant_id=context.tenant_id,
            basket_reference=basket_reference,
            line_reference=line_reference,
            sku_id=context.sku_id,
            branch_id=context.branch_id,
            locked_unit_price=resolved.unit_price,
            quantity=Decimal(str(context.quantity)),
            currency=resolved.currency,
            source=resolved.source,
            source_reference=resolved.reference,
            context_hash=resolved.context_hash,
            expires_at=timezone.now() + timedelta(minutes=minutes),
        )

    @staticmethod
    def active_lock(*, tenant_id, basket_reference: str, line_reference: str) -> PriceLock | None:
        """The live lock for a line, or None.

        Expiry is applied here rather than by callers, so no path can read a
        lock without checking whether it still holds.
        """
        lock = PriceLock.all_objects.filter(
            tenant_id=tenant_id,
            basket_reference=basket_reference,
            line_reference=line_reference,
            status=PriceLock.Status.ACTIVE,
        ).first()
        if lock is None:
            return None
        if not lock.is_live:
            lock.status = PriceLock.Status.EXPIRED
            lock.save(update_fields=["status", "updated_at"])
            return None
        return lock

    @staticmethod
    @transaction.atomic
    def invalidate_basket(*, tenant_id, basket_reference: str, reason: str) -> int:
        """Drop every lock on a basket that has materially changed.

        Called when the customer, the branch or the insurance selection
        changes. Those alter what the correct price is, so every locked figure
        on the basket is now answering the wrong question.
        """
        return PriceLock.all_objects.filter(
            tenant_id=tenant_id,
            basket_reference=basket_reference,
            status=PriceLock.Status.ACTIVE,
        ).update(
            status=PriceLock.Status.INVALIDATED,
            invalidation_reason=reason,
            updated_at=timezone.now(),
        )

    @classmethod
    def verify(cls, *, context: PricingContext, resolved, basket_reference: str,
               line_reference: str) -> PriceChange | None:
        """Compare the locked price with the current one.

        Returns the disagreement, or None. A lock whose context no longer
        matches the basket is treated as absent rather than as agreement: the
        quantity changed, so the locked unit price was quoted for a different
        sale.
        """
        lock = cls.active_lock(
            tenant_id=context.tenant_id,
            basket_reference=basket_reference,
            line_reference=line_reference,
        )
        if lock is None:
            return None

        if not lock.matches(resolved.context_hash):
            lock.status = PriceLock.Status.INVALIDATED
            lock.invalidation_reason = (
                "The basket changed after this price was quoted, so the quote no "
                "longer describes this sale."
            )
            lock.save(update_fields=["status", "invalidation_reason", "updated_at"])
            return None

        if money(lock.locked_unit_price) == money(resolved.unit_price):
            return None

        return PriceChange(
            line_reference=line_reference,
            locked_price=money(lock.locked_unit_price),
            current_price=money(resolved.unit_price),
            reason=f"the {resolved.source} price changed after the quote",
        )

    @classmethod
    def assert_unchanged(cls, *, context: PricingContext, resolved, basket_reference: str,
                         line_reference: str, acknowledged: bool = False) -> None:
        """Refuse to proceed on a moved price unless somebody has acknowledged it.

        The acknowledgement is the point. An operator who has seen both figures
        and chosen may continue; a till that charges the difference silently may
        not.
        """
        change = cls.verify(
            context=context, resolved=resolved,
            basket_reference=basket_reference, line_reference=line_reference,
        )
        if change is None:
            return
        if acknowledged:
            return
        raise PriceChangedAtCheckout([change])

    @staticmethod
    @transaction.atomic
    def consume(*, lock: PriceLock) -> PriceLock:
        """Mark a lock as spent once the line is paid for.

        A consumed lock cannot be reused: it held a price for one sale, and a
        second sale is a second question.
        """
        if lock.status != PriceLock.Status.ACTIVE:
            raise ValidationError(
                f"A {lock.status} price lock cannot be consumed."
            )
        lock.status = PriceLock.Status.CONSUMED
        lock.save(update_fields=["status", "updated_at"])
        return lock
