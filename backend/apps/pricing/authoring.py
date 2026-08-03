"""Scoped price-book authoring.

`PriceBookVersionService.save_tenant_retail_draft` creates exactly one shape of
book: TENANT scope, RETAIL type. The model has supported BRANCH, INSURER,
INSURANCE_PLAN, CUSTOMER_SEGMENT and PROMOTIONAL all along, and
`PriceResolutionService` already ranks them -- there was simply no way to
create one.

This module creates them. It does **not** resolve prices: `PriceResolutionService`
owns precedence, its ranks are total and explicit, and a second implementation
here would be a second answer to "what does this cost?".

The lifecycle is the load-bearing part:

    DRAFT -> UNDER_REVIEW -> APPROVED -> ACTIVE -> SUPERSEDED
                                            |
                                            +---> EXPIRED

Entries may only be written while a version is DRAFT. Once a version is ACTIVE
it is what customers were charged, so editing it in place would rewrite history
that receipts and claims already reference.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.pricing.models import PriceAssignment, PriceBook, PriceBookEntry, PriceBookVersion

PENNY = Decimal("0.01")

Status = PriceBookVersion.Status
ScopeType = PriceBook.ScopeType
PriceType = PriceBook.PriceType

#: Versions whose entries may still be edited.
EDITABLE_STATUSES = frozenset({Status.DRAFT})

#: Versions that are or have been in force. Immutable.
IN_FORCE_STATUSES = frozenset({Status.ACTIVE, Status.SUPERSEDED, Status.EXPIRED})

#: Which scope types require a concrete target, and the PriceAssignment field
#: that carries it. TENANT needs none -- it is the whole tenant.
SCOPE_TARGET_FIELDS = {
    ScopeType.BRANCH: "branch",
    ScopeType.BRANCH_GROUP: "branch_group",
    ScopeType.REGION: "region",
    ScopeType.CUSTOMER_SEGMENT: "customer_segment",
    ScopeType.CUSTOMER: "customer_id",
    ScopeType.INSURER: "insurer_id",
    ScopeType.INSURANCE_PLAN: "insurance_plan_id",
}


def _quantize(value, field: str) -> Decimal:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a decimal number.") from exc
    if not amount.is_finite():
        raise ValidationError(f"{field} must be finite.")
    if amount < 0:
        # A negative price would pay the customer to take the stock.
        raise ValidationError(f"{field} cannot be negative.")
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


class PriceBookService:
    """Creates and governs scoped price books."""

    @staticmethod
    @transaction.atomic
    def create_book(
        *,
        tenant,
        code: str,
        name: str,
        price_type: str = PriceType.RETAIL,
        scope_type: str = ScopeType.TENANT,
        currency: str = "KES",
        priority: int = 0,
        tax_inclusive: bool = True,
        actor=None,
    ) -> PriceBook:
        """Create a price book. Idempotent on (tenant, code)."""
        code = str(code or "").strip()
        name = str(name or "").strip()
        if not code:
            raise ValidationError("A price book requires a code.")
        if not name:
            raise ValidationError("A price book requires a name.")
        if price_type not in PriceType.values:
            raise ValidationError(
                f"Unknown price type {price_type!r}. Known: {', '.join(PriceType.values)}"
            )
        if scope_type not in ScopeType.values:
            raise ValidationError(
                f"Unknown scope type {scope_type!r}. Known: {', '.join(ScopeType.values)}"
            )
        if not currency or len(currency) != 3:
            raise ValidationError("A price book requires a three-letter currency code.")

        existing = PriceBook.all_objects.filter(tenant=tenant, code=code).first()
        if existing is not None:
            return existing

        book = PriceBook.all_objects.create(
            tenant=tenant, code=code, name=name, price_type=price_type,
            scope_type=scope_type, currency=currency.upper(), priority=priority,
            tax_inclusive=tax_inclusive, is_active=True,
        )
        log_audit(
            tenant_id=tenant.pk, action="PRICE_BOOK_CREATED", model_name="PriceBook",
            object_id=book.pk, actor_id=getattr(actor, "id", None),
            metadata={"code": code, "scope_type": scope_type, "price_type": price_type},
        )
        return book

    @staticmethod
    @transaction.atomic
    def assign_scope(
        *, book: PriceBook, branch=None, insurer_id: str = "", insurance_plan_id: str = "",
        customer_segment: str = "", branch_group: str = "", region: str = "",
        customer_id: str = "", priority: int = 0, valid_from: date | None = None,
        valid_to: date | None = None, actor=None,
    ) -> PriceAssignment:
        """Bind a book to the thing it applies to.

        A BRANCH-scoped book with no branch assignment applies to nothing, and
        would sit in the catalogue looking configured. So the target required
        by the scope must be supplied, and a branch must belong to the tenant.
        """
        required = SCOPE_TARGET_FIELDS.get(book.scope_type)
        supplied = {
            "branch": branch, "branch_group": branch_group, "region": region,
            "customer_segment": customer_segment, "customer_id": customer_id,
            "insurer_id": insurer_id, "insurance_plan_id": insurance_plan_id,
        }
        if required is not None and not supplied.get(required):
            raise ValidationError(
                f"A {book.scope_type}-scoped price book requires a {required}."
            )
        if branch is not None and branch.tenant_id != book.tenant_id:
            raise ValidationError("The branch belongs to a different tenant than the book.")
        if valid_from and valid_to and valid_to < valid_from:
            raise ValidationError("A price assignment cannot end before it begins.")

        assignment, _ = PriceAssignment.all_objects.update_or_create(
            tenant=book.tenant, price_book=book, scope_type=book.scope_type,
            branch=branch, branch_group=branch_group, region=region,
            customer_segment=customer_segment, customer_id=customer_id,
            insurer_id=insurer_id, insurance_plan_id=insurance_plan_id,
            defaults={
                "priority": priority, "valid_from": valid_from,
                "valid_to": valid_to, "is_active": True,
            },
        )
        return assignment

    # -- versions ----------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create_draft(
        *, book: PriceBook, effective_from: date, effective_to: date | None = None,
        actor=None,
    ) -> PriceBookVersion:
        """Open a draft version of a book.

        Refuses a second open draft: two drafts make "which one am I editing?"
        a question the caller has to answer, and the wrong answer publishes the
        wrong prices.
        """
        if effective_from is None:
            raise ValidationError("A price book version requires an effective-from date.")
        if effective_to is not None and effective_to < effective_from:
            raise ValidationError("A price book version cannot end before it takes effect.")

        open_draft = PriceBookVersion.all_objects.filter(
            tenant=book.tenant, price_book=book,
            status__in=[Status.DRAFT, Status.UNDER_REVIEW, Status.APPROVED],
        ).order_by("version_number").first()
        if open_draft is not None:
            return open_draft

        last = (
            PriceBookVersion.all_objects.filter(tenant=book.tenant, price_book=book)
            .order_by("-version_number").first()
        )
        version = PriceBookVersion.all_objects.create(
            tenant=book.tenant, price_book=book,
            version_number=(last.version_number + 1) if last else 1,
            status=Status.DRAFT, effective_from=effective_from, effective_to=effective_to,
            created_by=actor,
        )
        return version

    @staticmethod
    @transaction.atomic
    def add_or_update_entry(
        *, version: PriceBookVersion, sku, unit_price, minimum_allowed_price=None,
        tax_inclusive: bool | None = None, actor=None,
    ) -> PriceBookEntry:
        """Set a SKU's price in a draft version.

        Refused once the version has left DRAFT. An ACTIVE version is what
        customers were charged; editing it would change a price after the fact,
        and receipts and insurance claims already quote it.
        """
        if version.status not in EDITABLE_STATUSES:
            raise ValidationError(
                f"Version {version.version_number} is {version.status} and cannot be "
                "edited. Create a new draft version instead."
            )
        if sku is None:
            raise ValidationError("A price entry requires a SKU.")
        if sku.tenant_id != version.tenant_id:
            raise ValidationError("The SKU belongs to a different tenant than the price book.")

        price = _quantize(unit_price, "unit_price")
        floor = (
            _quantize(minimum_allowed_price, "minimum_allowed_price")
            if minimum_allowed_price is not None else None
        )
        if floor is not None and floor > price:
            raise ValidationError("The minimum allowed price cannot exceed the unit price.")

        entry, _ = PriceBookEntry.all_objects.update_or_create(
            tenant=version.tenant, version=version, sku=sku,
            defaults={
                "unit_price": price,
                "minimum_allowed_price": floor,
                "tax_inclusive": (
                    version.price_book.tax_inclusive if tax_inclusive is None else tax_inclusive
                ),
            },
        )
        return entry

    @staticmethod
    @transaction.atomic
    def submit(*, version: PriceBookVersion, actor) -> PriceBookVersion:
        """Send a draft for review."""
        if actor is None:
            raise PermissionDenied("Submitting a price book version requires a named actor.")
        if version.status != Status.DRAFT:
            raise ValidationError(f"Only a DRAFT version can be submitted; this is {version.status}.")
        if not PriceBookEntry.all_objects.filter(tenant=version.tenant, version=version).exists():
            # An empty book that reaches ACTIVE contributes no candidate to
            # resolution, so the price silently falls through to a lower-ranked
            # source and nobody sees an error.
            raise ValidationError(
                f"Version {version.version_number} has no price entries and cannot be "
                "submitted."
            )
        version.status = Status.UNDER_REVIEW
        version.save(update_fields=["status", "updated_at"])
        return version

    @staticmethod
    @transaction.atomic
    def approve(*, version: PriceBookVersion, approver) -> PriceBookVersion:
        """Approve a submitted version.

        The approver may not be the author. Prices are a financial control, and
        a single person drafting and approving their own price change is the
        control this exists to provide.
        """
        if approver is None:
            raise PermissionDenied("Approving a price book version requires a named approver.")
        if version.status != Status.UNDER_REVIEW:
            raise ValidationError(
                f"Only an UNDER_REVIEW version can be approved; this is {version.status}."
            )
        if version.created_by_id and str(version.created_by_id) == str(approver.id):
            raise PermissionDenied(
                "The approver must differ from the author of the price book version."
            )
        version.status = Status.APPROVED
        version.approved_by = approver
        version.approved_at = timezone.now()
        version.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        log_audit(
            tenant_id=version.tenant_id, action="PRICE_BOOK_VERSION_APPROVED",
            model_name="PriceBookVersion", object_id=version.pk, actor_id=approver.id,
            metadata={"price_book": version.price_book.code,
                      "version": version.version_number},
        )
        return version

    @staticmethod
    @transaction.atomic
    def activate(*, version: PriceBookVersion, actor) -> PriceBookVersion:
        """Put an approved version into force, superseding the incumbent.

        Supersession is automatic and atomic. Two ACTIVE versions of one book
        would give resolution two candidates at identical rank, which
        `PriceResolutionService` treats as fatal ambiguity -- correctly, but the
        failure would surface at the till.
        """
        if actor is None:
            raise PermissionDenied("Activating a price book version requires a named actor.")
        if version.status != Status.APPROVED:
            raise ValidationError(
                f"Only an APPROVED version can be activated; this is {version.status}."
            )

        PriceBookVersion.all_objects.filter(
            tenant=version.tenant, price_book=version.price_book, status=Status.ACTIVE
        ).exclude(pk=version.pk).update(status=Status.SUPERSEDED)

        version.status = Status.ACTIVE
        version.published_at = timezone.now()
        version.save(update_fields=["status", "published_at", "updated_at"])
        log_audit(
            tenant_id=version.tenant_id, action="PRICE_BOOK_VERSION_ACTIVATED",
            model_name="PriceBookVersion", object_id=version.pk, actor_id=actor.id,
            metadata={"price_book": version.price_book.code,
                      "version": version.version_number},
        )
        return version

    @staticmethod
    @transaction.atomic
    def close(*, version: PriceBookVersion, actor, reason: str) -> PriceBookVersion:
        """Take a version out of force without deleting it."""
        if actor is None:
            raise PermissionDenied("Closing a price book version requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Closing a price book version requires a reason.")
        if version.status != Status.ACTIVE:
            raise ValidationError(f"Only an ACTIVE version can be closed; this is {version.status}.")

        version.status = Status.EXPIRED
        version.save(update_fields=["status", "updated_at"])
        return version

    # -- convenience -------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def publish_priced_book(
        *,
        tenant,
        code: str,
        name: str,
        prices: dict,
        author,
        approver,
        effective_from: date,
        price_type: str = PriceType.RETAIL,
        scope_type: str = ScopeType.TENANT,
        priority: int = 0,
        branch=None,
        insurer_id: str = "",
        insurance_plan_id: str = "",
        customer_segment: str = "",
        currency: str = "KES",
    ) -> PriceBookVersion:
        """Create, price, approve and activate a book in one governed pass.

        Every step still goes through the lifecycle above -- this only spares
        callers from repeating six calls. The author/approver split is
        preserved, so a caller cannot use this to bypass segregation of duties.

        Idempotent: re-running with the same code returns the active version
        rather than opening a second one.
        """
        if author is None or approver is None:
            raise PermissionDenied("Publishing a price book requires an author and an approver.")
        if str(getattr(author, "id", "")) == str(getattr(approver, "id", "")):
            raise PermissionDenied("The approver must differ from the author.")

        book = PriceBookService.create_book(
            tenant=tenant, code=code, name=name, price_type=price_type,
            scope_type=scope_type, currency=currency, priority=priority, actor=author,
        )
        if scope_type != ScopeType.TENANT:
            PriceBookService.assign_scope(
                book=book, branch=branch, insurer_id=insurer_id,
                insurance_plan_id=insurance_plan_id, customer_segment=customer_segment,
                priority=priority, actor=author,
            )

        active = PriceBookVersion.all_objects.filter(
            tenant=tenant, price_book=book, status=Status.ACTIVE
        ).first()
        if active is not None:
            return active

        version = PriceBookService.create_draft(
            book=book, effective_from=effective_from, actor=author
        )
        if version.status == Status.DRAFT:
            for sku, unit_price in sorted(prices.items(), key=lambda kv: kv[0].sku_code):
                PriceBookService.add_or_update_entry(
                    version=version, sku=sku, unit_price=unit_price, actor=author
                )
            PriceBookService.submit(version=version, actor=author)
        if version.status == Status.UNDER_REVIEW:
            PriceBookService.approve(version=version, approver=approver)
        if version.status == Status.APPROVED:
            PriceBookService.activate(version=version, actor=approver)
        return version
