"""Gathering price candidates from the database, and recording what was charged.

The resolution engine decides between candidates. This is what finds them, and
the finding is where branch sparsity lives: a branch is offered its own override
book *and* the tenant book it inherits, and precedence picks. That is why a
branch with no override still gets a price without anyone copying four hundred
lists.

Only published, in-date versions are offered. A draft price is somebody's work
in progress, and a till that could charge from one would be charging from an
unapproved figure.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    AppliedPriceSnapshot,
    ManualPriceOverride,
    PriceAssignment,
    PriceBook,
    PriceBookEntry,
    PriceBookVersion,
)
from .resolution import (
    PriceCandidate,
    PriceResolutionService,
    PriceSource,
    PricingContext,
    money,
)

#: Which price source a book's scope contributes to. Kept as a mapping rather
#: than branching, so adding a scope means adding a line here and a rank in
#: PriceSource, and forgetting either is a visible gap rather than silent
#: mis-ranking.
SCOPE_TO_SOURCE = {
    PriceBook.ScopeType.BRANCH: PriceSource.BRANCH_PRICE,
    PriceBook.ScopeType.BRANCH_GROUP: PriceSource.BRANCH_GROUP_PRICE,
    PriceBook.ScopeType.REGION: PriceSource.BRANCH_GROUP_PRICE,
    PriceBook.ScopeType.TENANT: PriceSource.TENANT_PRICE,
    PriceBook.ScopeType.CUSTOMER: PriceSource.CUSTOMER_CONTRACT,
    PriceBook.ScopeType.CUSTOMER_SEGMENT: PriceSource.CUSTOMER_SEGMENT,
    PriceBook.ScopeType.INSURER: PriceSource.INSURANCE_TARIFF,
    PriceBook.ScopeType.INSURANCE_PLAN: PriceSource.INSURANCE_TARIFF,
}


class PriceCatalogue:
    """Finds the price candidates that apply to a context."""

    @staticmethod
    def assignments_for(*, context: PricingContext):
        """Assignments whose scope matches this context.

        A branch assignment matches only its own branch; a tenant assignment
        matches every branch. That asymmetry is the inheritance: the branch is
        offered both, and precedence prefers the specific one.
        """
        candidates = PriceAssignment.all_objects.filter(
            tenant_id=context.tenant_id, is_active=True
        ).select_related("price_book")

        matched = []
        for assignment in candidates:
            if not assignment.applies_on(context.service_date):
                continue

            scope = assignment.scope_type
            if scope == PriceBook.ScopeType.TENANT:
                matched.append(assignment)
            elif scope == PriceBook.ScopeType.BRANCH:
                if str(assignment.branch_id) == str(context.branch_id):
                    matched.append(assignment)
            elif scope in {PriceBook.ScopeType.BRANCH_GROUP, PriceBook.ScopeType.REGION}:
                group = assignment.branch_group or assignment.region
                if group and group == context.branch_group_id:
                    matched.append(assignment)
            elif scope == PriceBook.ScopeType.CUSTOMER:
                if context.customer_id and assignment.customer_id == str(context.customer_id):
                    matched.append(assignment)
            elif scope == PriceBook.ScopeType.CUSTOMER_SEGMENT:
                if context.customer_segment and assignment.customer_segment == context.customer_segment:
                    matched.append(assignment)
            elif scope == PriceBook.ScopeType.INSURER:
                if context.insurer_id and assignment.insurer_id == str(context.insurer_id):
                    matched.append(assignment)
            elif scope == PriceBook.ScopeType.INSURANCE_PLAN:
                if context.insurance_plan_id and assignment.insurance_plan_id == str(
                    context.insurance_plan_id
                ):
                    matched.append(assignment)
        return matched

    @staticmethod
    def live_version(*, price_book: PriceBook, service_date):
        """The published version in force on the date.

        Drafts and cancelled versions are never offered: a till charging from a
        draft is charging a figure nobody approved. Where several published
        versions cover the date the highest number wins, since that is the
        latest revision.
        """
        versions = [
            version
            for version in PriceBookVersion.all_objects.filter(
                tenant_id=price_book.tenant_id,
                price_book=price_book,
                status__in=["ACTIVE", "SCHEDULED", "SUPERSEDED", "EXPIRED"],
            )
            if version.applies_on(service_date)
        ]
        if not versions:
            return None
        return max(versions, key=lambda version: version.version_number)

    @classmethod
    def candidates_for(cls, *, context: PricingContext) -> list[PriceCandidate]:
        """Every price that could apply, unranked.

        Includes an approved manual override for this transaction when one
        exists, so the override competes through the same precedence ladder as
        everything else rather than bypassing resolution entirely.
        """
        found: list[PriceCandidate] = []

        for assignment in cls.assignments_for(context=context):
            book = assignment.price_book
            if not book.is_active:
                continue
            source = SCOPE_TO_SOURCE.get(book.scope_type)
            if source is None:
                # An unmapped scope contributes nothing rather than defaulting
                # to a rank. A wrong rank silently mis-prices; a gap is visible.
                continue

            version = cls.live_version(price_book=book, service_date=context.service_date)
            if version is None:
                continue

            entries = PriceBookEntry.all_objects.filter(
                tenant_id=context.tenant_id, version=version, sku_id=context.sku_id
            )
            for entry in entries:
                if entry.maximum_quantity is not None and Decimal(
                    str(context.quantity)
                ) > Decimal(str(entry.maximum_quantity)):
                    continue
                name, rank = source
                found.append(
                    PriceCandidate(
                        source=name,
                        # A book's own priority nudges it within its scope, so
                        # two books of one scope resolve deterministically
                        # instead of reaching the ambiguity refusal.
                        rank=rank - min(max(book.priority, 0), 5),
                        unit_price=money(entry.unit_price),
                        reference=f"{book.code}:v{version.version_number}",
                        version=str(version.version_number),
                        currency=book.currency,
                        effective_from=version.effective_from,
                        effective_to=version.effective_to,
                        minimum_quantity=Decimal(str(entry.minimum_quantity)),
                        tax_inclusive=entry.tax_inclusive,
                    )
                )

        override = cls.usable_override(context=context)
        if override is not None:
            name, rank = PriceSource.MANUAL_OVERRIDE
            found.append(
                PriceCandidate(
                    source=name,
                    rank=rank,
                    unit_price=money(override.override_price),
                    reference=f"override:{override.pk}",
                    currency=context.currency,
                )
            )
        return found

    @staticmethod
    def usable_override(*, context: PricingContext, transaction_reference: str = ""):
        """An approved, unexpired override for this transaction, or None.

        Requested and rejected overrides are not usable, and neither is an
        expired one -- an override authorised an hour ago for a damaged box
        should not still be reducing prices tomorrow.
        """
        reference = transaction_reference or getattr(context, "transaction_reference", "")
        if not reference:
            return None
        override = ManualPriceOverride.all_objects.filter(
            tenant_id=context.tenant_id,
            sku_id=context.sku_id,
            branch_id=context.branch_id,
            transaction_reference=reference,
        ).order_by("-created_at").first()
        if override is None or not override.is_usable:
            return None
        return override

    # ---------------------------------------------------------------- pricing

    @classmethod
    def price(cls, *, context: PricingContext):
        """Resolve a price from the database for this context."""
        return PriceResolutionService.resolve(
            candidates=cls.candidates_for(context=context), context=context
        )

    @classmethod
    @transaction.atomic
    def record_applied_price(cls, *, context: PricingContext, resolved, line_reference: str,
                             line_type: str = "SALE", discount=None, tax=None) -> AppliedPriceSnapshot:
        """Write what this line was charged.

        One snapshot per line, enforced by a unique constraint. A second write
        for the same line would mean the line has two prices, and nobody could
        say which the customer paid.
        """
        existing = AppliedPriceSnapshot.all_objects.filter(
            tenant_id=context.tenant_id, line_reference=line_reference, line_type=line_type
        ).first()
        if existing is not None:
            raise ValidationError(
                f"{line_type} line {line_reference} already carries an applied price of "
                f"{existing.unit_price}. A line has one price."
            )

        return AppliedPriceSnapshot.all_objects.create(
            tenant_id=context.tenant_id,
            line_reference=line_reference,
            line_type=line_type,
            sku_id=context.sku_id,
            branch_id=context.branch_id,
            quantity=Decimal(str(context.quantity)),
            currency=resolved.currency,
            unit_price=resolved.unit_price,
            line_total=PriceResolutionService.line_total(
                unit_price=resolved.unit_price, quantity=context.quantity
            ),
            discount_amount=money(discount),
            tax_amount=money(tax),
            source=resolved.source,
            source_reference=resolved.reference,
            resolution_trace=list(resolved.considered),
            context_hash=resolved.context_hash,
        )
