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

from apps.procurement.models import GoodsReceipt, SupplierReturn, SupplierReturnLine


class SupplierReturnService:
    """Requests and progresses returns to a supplier."""

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
            reason=reason or supplier_return.reason,
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
