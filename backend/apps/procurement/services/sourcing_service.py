"""Competitive sourcing: request for quotation, quotation, award.

The tables and two half-methods existed; the cycle did not. There was no way to
submit a quotation at all, so an RFQ could be raised and then awarded to nothing
-- and `award_quotation` never checked that the quotation it was handed belonged
to the RFQ it was awarding.

That is the shape of a procurement fraud rather than a bug: award a tender to a
quote from a different tender, or to one submitted after the close, and the
paperwork still reads as a competitive process.

This service owns the whole cycle and refuses each of those.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.procurement.models import (
    QuotationAward,
    RequestForQuotation,
    RFQLine,
    Supplier,
    SupplierQuotation,
    SupplierQuotationLine,
)
from apps.workflows.service import emit_event


class SourcingService:
    """Runs a competitive tender from request to award."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"

    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"

    #: Only a supplier governance has cleared may be invited to quote or be
    #: awarded. Suspension exists to stop new commitments.
    QUOTABLE_STATUSES = (Supplier.Status.APPROVED, Supplier.Status.ACTIVE)

    # ── request ──────────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def create_rfq(*, tenant, title: str, lines_data, closing_date, actor=None) -> RequestForQuotation:
        """Raise a request for quotation.

        The number is derived from the highest existing sequence rather than a
        row count. A count repeats a number as soon as any RFQ is removed, and
        two raised in the same transaction would collide.
        """
        if not str(title or "").strip():
            raise ValidationError({"title": "A request for quotation requires a title."})
        if not lines_data:
            raise ValidationError(
                {"lines_data": "A request for quotation requires at least one line."}
            )
        if closing_date is None:
            raise ValidationError({"closing_date": "A closing date is required."})
        if closing_date < timezone.localdate():
            # A tender that closed before it opened cannot receive a quotation,
            # so every award against it would be out of time by construction.
            raise ValidationError(
                {"closing_date": "The closing date cannot be in the past."}
            )

        prefix = f"RFQ-{timezone.now().strftime('%Y%m%d')}-"
        last = (
            RequestForQuotation.all_objects.filter(
                tenant=tenant, rfq_number__startswith=prefix
            )
            .order_by("-rfq_number")
            .values_list("rfq_number", flat=True)
            .first()
        )
        sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1

        rfq = RequestForQuotation.all_objects.create(
            tenant=tenant,
            rfq_number=f"{prefix}{sequence:04d}",
            title=title.strip(),
            closing_date=closing_date,
            status=SourcingService.OPEN,
        )
        for line in lines_data:
            try:
                quantity = Decimal(str(line.get("requested_quantity")))
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise ValidationError(
                    {"lines_data": "Every line requires a numeric requested quantity."}
                ) from exc
            if quantity <= 0:
                raise ValidationError(
                    {"lines_data": "Every line requires a positive requested quantity."}
                )
            RFQLine.all_objects.create(
                tenant=tenant, rfq=rfq, sku=line["sku"], requested_quantity=quantity
            )

        emit_event(
            tenant_id=str(tenant.pk), aggregate_type="RequestForQuotation",
            aggregate_id=str(rfq.pk), event_type="RequestForQuotationRaised",
            payload={"rfq_number": rfq.rfq_number, "closing_date": str(closing_date)},
        )
        return rfq

    # ── quotation ────────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def submit_quotation(
        *, rfq: RequestForQuotation, supplier: Supplier, quotation_reference: str,
        lines_data, valid_until, actor=None,
    ) -> SupplierQuotation:
        """Record a supplier's priced response to an RFQ.

        This did not exist. Without it the cycle could not run: an RFQ could be
        raised and awarded, but nothing could be quoted, so an award was against
        a quotation that had to be created by some other route entirely.

        The total is summed from the lines rather than accepted from the caller.
        A quoted total that disagrees with its own lines is the number an award
        gets compared on, and the one nobody notices is wrong.
        """
        if rfq.status != SourcingService.OPEN:
            raise ValidationError(
                f"This request for quotation is {rfq.status} and is no longer "
                "accepting quotations."
            )
        if timezone.localdate() > rfq.closing_date:
            # Accepting a late quote and awarding it is the simplest way to
            # make a tender look competitive while it is not.
            raise ValidationError(
                f"This request for quotation closed on {rfq.closing_date}."
            )
        if supplier.status not in SourcingService.QUOTABLE_STATUSES:
            raise ValidationError(
                f"{supplier.supplier_code} is {supplier.status} and cannot quote."
            )
        if not str(quotation_reference or "").strip():
            raise ValidationError(
                {"quotation_reference": "A quotation reference is required."}
            )
        if not lines_data:
            raise ValidationError({"lines_data": "A quotation requires at least one line."})
        if valid_until is None:
            # A quoted price with no expiry is one the supplier can disown later
            # and one a buyer can hold them to forever. Neither is a quotation.
            raise ValidationError(
                {"valid_until": "A quotation must state how long the price holds."}
            )
        if valid_until < rfq.closing_date:
            # It would expire before the tender even closes, so it could never
            # be awarded.
            raise ValidationError(
                {
                    "valid_until": (
                        f"The price must hold at least until the tender closes on "
                        f"{rfq.closing_date}."
                    )
                }
            )

        existing = SupplierQuotation.all_objects.filter(rfq=rfq, supplier=supplier).first()
        if existing is not None:
            # One quotation per supplier per tender. A second one silently
            # competing with the first makes "the lowest quote" ambiguous.
            raise ValidationError(
                f"{supplier.supplier_code} has already quoted on {rfq.rfq_number}."
            )

        quoted_skus = {line["sku"].pk for line in lines_data}
        requested_skus = set(
            RFQLine.all_objects.filter(rfq=rfq).values_list("sku_id", flat=True)
        )
        unrequested = quoted_skus - requested_skus
        if unrequested:
            raise ValidationError(
                "A quotation may only price products the request asked for."
            )

        # Coerced here rather than trusted. Line values arrive from a DictField,
        # so a quantity or price crosses this boundary as whatever JSON carried
        # -- usually a string. Comparing that against zero raises TypeError and
        # the guard never runs.
        total = Decimal("0.00")
        priced = []
        for line in lines_data:
            try:
                quantity = Decimal(str(line.get("quoted_quantity")))
                unit_cost = Decimal(str(line.get("quoted_unit_cost")))
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise ValidationError(
                    "Every quotation line requires a numeric quantity and unit cost."
                ) from exc
            if quantity <= 0:
                raise ValidationError("Every quotation line requires a positive quantity.")
            if unit_cost < 0:
                raise ValidationError("A quotation line cannot have a negative unit cost.")
            total += unit_cost * quantity
            priced.append((line["sku"], quantity, unit_cost))

        quotation = SupplierQuotation.all_objects.create(
            tenant=rfq.tenant, rfq=rfq, supplier=supplier,
            quotation_reference=quotation_reference.strip(),
            total_quoted_cost=total, valid_until=valid_until,
            status=SourcingService.SUBMITTED,
        )
        for sku, quantity, unit_cost in priced:
            SupplierQuotationLine.all_objects.create(
                tenant=rfq.tenant, quotation=quotation, sku=sku,
                quoted_quantity=quantity, quoted_unit_cost=unit_cost,
            )

        emit_event(
            tenant_id=str(rfq.tenant_id), aggregate_type="SupplierQuotation",
            aggregate_id=str(quotation.pk), event_type="SupplierQuotationSubmitted",
            payload={
                "rfq_number": rfq.rfq_number,
                "supplier_code": supplier.supplier_code,
                "total_quoted_cost": str(total),
            },
        )
        return quotation

    # ── award ────────────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def award_quotation(
        *, rfq: RequestForQuotation, winning_quotation: SupplierQuotation,
        awarded_by, justification: str = "",
    ) -> QuotationAward:
        """Award a tender to one of its own quotations.

        The previous implementation checked nothing. It would award an RFQ to a
        quotation belonging to a different RFQ, award an already-awarded tender
        a second time, or award to a supplier suspended since quoting -- and the
        paperwork would still read as a competitive process.
        """
        if winning_quotation.rfq_id != rfq.pk:
            raise ValidationError(
                f"{winning_quotation.quotation_reference} was submitted against a "
                "different request for quotation and cannot win this one."
            )
        if rfq.status == SourcingService.AWARDED:
            raise ValidationError(f"{rfq.rfq_number} has already been awarded.")
        if rfq.status == SourcingService.CANCELLED:
            raise ValidationError(f"{rfq.rfq_number} was cancelled.")
        if winning_quotation.status != SourcingService.SUBMITTED:
            raise ValidationError(
                f"That quotation is {winning_quotation.status} and cannot be awarded."
            )
        if winning_quotation.supplier.status not in SourcingService.QUOTABLE_STATUSES:
            # Suspended between quoting and awarding: the award would commit to
            # a supplier governance has since stopped.
            raise ValidationError(
                f"{winning_quotation.supplier.supplier_code} is "
                f"{winning_quotation.supplier.status} and cannot be awarded to."
            )

        # Awarding anything other than the lowest total is legitimate -- quality,
        # lead time, capacity -- but it has to be said out loud, because an
        # unexplained award above the lowest quote is what an audit looks for.
        lowest = (
            SupplierQuotation.all_objects.filter(
                rfq=rfq, status=SourcingService.SUBMITTED
            )
            .order_by("total_quoted_cost")
            .first()
        )
        if (
            lowest is not None
            and lowest.pk != winning_quotation.pk
            and not str(justification or "").strip()
        ):
            raise ValidationError(
                {
                    "justification": (
                        f"{winning_quotation.quotation_reference} is not the lowest "
                        f"quotation ({lowest.quotation_reference} at "
                        f"{lowest.total_quoted_cost}). Awarding above the lowest "
                        "quote requires a stated reason."
                    )
                }
            )

        award = QuotationAward.all_objects.create(
            tenant=rfq.tenant, rfq=rfq, winning_quotation=winning_quotation,
            awarded_by=awarded_by,
        )
        rfq.status = SourcingService.AWARDED
        rfq.save(update_fields=["status", "updated_at"])
        winning_quotation.status = SourcingService.ACCEPTED
        winning_quotation.save(update_fields=["status", "updated_at"])

        # Everything else loses, explicitly. Leaving them SUBMITTED makes a
        # closed tender look like it is still running.
        SupplierQuotation.all_objects.filter(
            rfq=rfq, status=SourcingService.SUBMITTED
        ).exclude(pk=winning_quotation.pk).update(status=SourcingService.REJECTED)

        emit_event(
            tenant_id=str(rfq.tenant_id), aggregate_type="QuotationAward",
            aggregate_id=str(award.pk), event_type="QuotationAwarded",
            payload={
                "rfq_number": rfq.rfq_number,
                "supplier_code": winning_quotation.supplier.supplier_code,
                "total_quoted_cost": str(winning_quotation.total_quoted_cost),
                "lowest_quoted_cost": str(lowest.total_quoted_cost) if lowest else None,
                "justification": (justification or "").strip(),
            },
        )
        return award
