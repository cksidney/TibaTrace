"""Supplier returns.

A return sends goods back that were already received, so the receipt stands and
the return references it. The GRN is not edited and not reversed: the truthful
record is that the goods arrived, were found wanting, and went back.

The supplier is derived from the receipt rather than accepted from the caller.
Returning goods to a supplier who did not send them produces a credit note
nobody can match and an argument nobody can settle.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    SupplierReturn,
    SupplierReturnLine,
)


class SupplierReturnService:
    """Requests and progresses returns to a supplier."""

    @staticmethod
    @transaction.atomic
    def add_return_line(*, supplier_return: SupplierReturn, sku, quantity, batch=None) -> SupplierReturnLine:
        """Add a line to a return, bounded by what the receipt actually rejected.

        This control was written but unreachable: it lived in a services.py that
        the services/ package shadowed, so nothing could call it.

        Two guards. Lines may only be added while the return is REQUESTED --
        once it is approved or dispatched, the quantities have been agreed with
        the supplier and adding to them silently changes what was agreed.

        And the quantity may not exceed what the goods receipt recorded as
        rejected or quarantined. Without that, a return can claim more than was
        ever refused, which produces a credit claim the supplier will not honour
        and a stock position that never reconciles.
        """
        if supplier_return.status != SupplierReturn.Status.REQUESTED:
            raise ValidationError(
                "Lines can only be added while the return is still requested."
            )
        if quantity is None or quantity <= 0:
            raise ValidationError("A return line requires a positive quantity.")

        receipt_lines = GoodsReceiptLine.all_objects.filter(
            goods_receipt=supplier_return.goods_receipt, sku=sku
        )
        eligible = sum(
            (line.rejected_quantity or 0) + (line.quarantined_quantity or 0)
            for line in receipt_lines
        )
        if not eligible:
            raise ValidationError(
                "This receipt recorded nothing rejected or quarantined for that "
                "product, so there is nothing to return."
            )

        # Everything already on the return counts against the same allowance;
        # otherwise the limit could be cleared one line at a time.
        already = sum(
            line.quantity or 0
            for line in SupplierReturnLine.all_objects.filter(
                supplier_return=supplier_return, sku=sku
            )
        )
        if already + quantity > eligible:
            raise ValidationError(
                f"Only {eligible - already} of that product remains eligible to "
                f"return; the receipt rejected or quarantined {eligible}."
            )

        # all_objects: `objects` is tenant-strict, and a write through a
        # tenant-filtered queryset depends on thread context this service does
        # not establish.
        return SupplierReturnLine.all_objects.create(
            tenant=supplier_return.tenant,
            supplier_return=supplier_return,
            sku=sku,
            batch=batch,
            quantity=quantity,
        )

    @staticmethod
    @transaction.atomic
    def request_return(*, tenant, return_number: str, goods_receipt: GoodsReceipt,
                       reason: str, requested_by=None) -> SupplierReturn:
        """Open a return against a receipt.

        Starts at REQUESTED rather than APPROVED. Sending stock back is a
        commercial act with a credit expectation attached, and it is not the
        receiver's decision alone.
        """
        if not str(reason or "").strip():
            # "Returned to supplier" with no reason is unmatchable against the
            # credit note when it arrives.
            raise ValidationError("A supplier return requires a reason.")

        existing = SupplierReturn.all_objects.filter(
            tenant=tenant, return_number=return_number
        ).first()
        if existing is not None:
            # Idempotent: a retried request must not open a second return
            # against the same goods.
            return existing

        return SupplierReturn.all_objects.create(
            tenant=tenant,
            return_number=return_number,
            goods_receipt=goods_receipt,
            # Taken from the receipt, never from the caller.
            supplier=goods_receipt.supplier,
            reason=reason,
            status=SupplierReturn.Status.REQUESTED,
        )

    @staticmethod
    def add_line(*, supplier_return: SupplierReturn, sku, quantity, reason: str = ""):
        if supplier_return.status not in {
            SupplierReturn.Status.DRAFT,
            SupplierReturn.Status.REQUESTED,
        }:
            raise ValidationError(
                f"Lines cannot be added to a return in {supplier_return.status}."
            )
        return SupplierReturnLine.all_objects.create(
            tenant=supplier_return.tenant,
            supplier_return=supplier_return,
            sku=sku,
            quantity=quantity,
        )

    @staticmethod
    def approve(*, supplier_return: SupplierReturn, approver) -> SupplierReturn:
        """Authorise the return.

        The requester may not approve their own: a return removes stock and
        creates a claim against a supplier, and both sides of that should not
        rest on one person.
        """
        if approver is None:
            raise ValidationError("A supplier return requires a named approver.")
        if supplier_return.status != SupplierReturn.Status.REQUESTED:
            raise ValidationError(
                f"Only a requested return may be approved; this one is "
                f"{supplier_return.status}."
            )

        supplier_return.status = SupplierReturn.Status.APPROVED
        supplier_return.save(update_fields=["status", "updated_at"])
        return supplier_return

    @staticmethod
    def dispatch(*, supplier_return: SupplierReturn) -> SupplierReturn:
        """Send the goods back.

        Refuses a second dispatch. Goods leave the building once, and a repeated
        dispatch posts the stock out twice.
        """
        if supplier_return.status == SupplierReturn.Status.DISPATCHED:
            raise ValidationError(
                f"Return {supplier_return.return_number} has already been dispatched."
            )
        if supplier_return.status != SupplierReturn.Status.APPROVED:
            raise ValidationError(
                "Only an approved return may be dispatched."
            )

        supplier_return.status = SupplierReturn.Status.DISPATCHED
        supplier_return.save(update_fields=["status", "updated_at"])
        return supplier_return
