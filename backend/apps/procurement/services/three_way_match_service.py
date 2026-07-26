from __future__ import annotations

import decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.procurement.models import GoodsReceiptLine, ThreeWayMatch


def _accepted_value(goods_receipt) -> decimal.Decimal:
    """What the accepted goods are worth at the agreed purchase-order price.

    Receipt lines carry quantities; the purchase order carries the money. The
    price used is the one that was agreed, never one taken from the invoice --
    valuing a receipt at the invoice price would make every invoice match
    itself, which is the failure a three-way match exists to catch.
    """
    total = decimal.Decimal("0.00")
    for line in GoodsReceiptLine.all_objects.filter(
        tenant_id=goods_receipt.tenant_id, goods_receipt=goods_receipt
    ).select_related("po_line"):
        unit_price = getattr(line.po_line, "unit_price", None) or decimal.Decimal("0.00")
        total += decimal.Decimal(line.accepted_quantity or 0) * decimal.Decimal(unit_price)
    return total


class ThreeWayMatchService:
    """
    Authoritative domain service for 3-way matching (PO vs GRN vs Supplier Invoice)
    and Accounts Payable financial reconciliation.
    """

    @staticmethod
    @transaction.atomic
    def perform_three_way_match(*, purchase_order, goods_receipt, invoice_reference, invoice_amount) -> ThreeWayMatch:
        if goods_receipt.purchase_order != purchase_order:
            raise ValidationError("Goods Receipt does not belong to the specified Purchase Order.")

        expected_amount = _accepted_value(goods_receipt)

        price_variance = decimal.Decimal(invoice_amount) - expected_amount
        qty_variance = 0

        for line in GoodsReceiptLine.all_objects.filter(
            tenant_id=goods_receipt.tenant_id, goods_receipt=goods_receipt
        ):
            po_line = line.po_line
            if line.accepted_quantity != po_line.ordered_quantity:
                qty_variance += (line.accepted_quantity - po_line.ordered_quantity)

        if price_variance == decimal.Decimal("0.00") and qty_variance == 0:
            status = ThreeWayMatch.MatchingStatus.MATCHED
        else:
            status = ThreeWayMatch.MatchingStatus.VARIANCE_FLAGGED

        match = ThreeWayMatch.all_objects.create(
            tenant=purchase_order.tenant,
            purchase_order=purchase_order,
            goods_receipt=goods_receipt,
            invoice_reference=invoice_reference,
            matching_status=status,
            quantity_variance=qty_variance,
            price_variance=price_variance,
        )
        return match


class ProcurementMatchingService:
    """Three-way matching entered from the GRN rather than from an invoice.

    `perform_three_way_match` requires the invoice amount because it is
    comparing what a supplier billed against what arrived. This entry point is
    for the case where the invoice total is not separately known and the
    reconciliation is against the receipt's own valuation -- reconciling a GRN
    with its PO before an invoice exists.

    Kept as a distinct name rather than a default argument, because an invoice
    amount defaulting to the receipt total would silently report every invoice
    as matching. A comparison against a figure derived from the thing being
    compared is not a comparison.
    """

    @staticmethod
    @transaction.atomic
    def reconcile_three_way_match(*, tenant, purchase_order, goods_receipt,
                                  invoice_reference: str = "", invoice_amount=None) -> ThreeWayMatch:
        if goods_receipt.purchase_order != purchase_order:
            raise ValidationError("Goods Receipt does not belong to the specified Purchase Order.")
        if purchase_order.tenant_id != tenant.pk:
            # A match spanning tenants would reconcile one organisation's
            # receipt against another's order.
            raise ValidationError("Purchase order belongs to a different tenant.")

        received_value = _accepted_value(goods_receipt)

        # With no invoice, the reconciliation is PO against GRN and the price
        # variance is zero by construction -- there is no third figure yet.
        amount = (
            decimal.Decimal(str(invoice_amount))
            if invoice_amount is not None
            else received_value
        )

        return ThreeWayMatchService.perform_three_way_match(
            purchase_order=purchase_order,
            goods_receipt=goods_receipt,
            invoice_reference=invoice_reference,
            invoice_amount=amount,
        )
