from __future__ import annotations

import decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderRevision,
    PurchaseRequisition,
    PurchaseRequisitionLine,
    QuotationAward,
    RequestForQuotation,
    RFQLine,
    Supplier,
)
from apps.procurement.services.supplier_governance_service import SupplierGovernanceService


class ProcurementService:
    """
    Authoritative domain service for Requisitions, RFQs, Quotation Awards,
    PO Creation, Approval, and Immutable Revisions.
    """

    @staticmethod
    @transaction.atomic
    def create_requisition(*, tenant, requesting_branch, requester, requested_delivery_date=None,
                           requisition_number=None, lines_data=None, priority="NORMAL",
                           reason="", justification="") -> PurchaseRequisition:
        """Open an internal demand document.

        Starts DRAFT. A requisition is a request, and submitting it is a
        separate act by the requester -- creating one must not put it in front
        of an approver before its author has finished with it.

        Lines may be supplied here or added afterwards with add_line(); a UI
        builds them incrementally and an API sends them complete, and both are
        legitimate.
        """
        if requested_delivery_date is None:
            raise ValidationError("A requisition requires a required-by date.")

        requisition = PurchaseRequisition.all_objects.create(
            tenant=tenant,
            requisition_number=requisition_number or ProcurementService._next_requisition_number(tenant),
            requesting_branch=requesting_branch,
            requester=requester,
            requested_delivery_date=requested_delivery_date,
            priority=priority,
            justification=justification or reason,
            status=PurchaseRequisition.Status.DRAFT,
        )

        for item in lines_data or []:
            ProcurementService.add_line(
                requisition=requisition,
                sku=item["sku"],
                requested_quantity=item["requested_quantity"],
                estimated_unit_cost=item.get("estimated_unit_cost", decimal.Decimal("0.00")),
                reason=item.get("reason", ""),
                purchase_unit=item.get("purchase_unit", "pack"),
            )

        return requisition

    @staticmethod
    def _next_requisition_number(tenant) -> str:
        """A document number that does not collide under concurrency.

        A count()+1 sequence gives two simultaneous requisitions the same
        number, and the unique constraint then fails one of them at random.
        """
        return (
            f"REQ-{timezone.now().strftime('%Y%m%d')}-"
            f"{uuid.uuid4().hex[:8].upper()}"
        )

    @staticmethod
    @transaction.atomic
    def add_line(*, requisition, sku, requested_quantity,
                 estimated_unit_cost=decimal.Decimal("0.00"), reason="",
                 purchase_unit="pack") -> PurchaseRequisitionLine:
        """Add a demand line.

        Refused once the requisition has been approved: an approver signed off
        on a specific set of lines, and adding to it afterwards spends their
        authority on something they never saw.
        """
        if requisition.status not in {
            PurchaseRequisition.Status.DRAFT,
            PurchaseRequisition.Status.SUBMITTED,
        }:
            raise ValidationError(
                f"Lines cannot be added to a requisition in {requisition.status}."
            )
        return PurchaseRequisitionLine.all_objects.create(
            tenant=requisition.tenant,
            requisition=requisition,
            sku=sku,
            requested_quantity=requested_quantity,
            # Outstanding starts as the full request: nothing has been ordered
            # against this line yet, and a zero default would make the line look
            # already satisfied to any replenishment calculation reading it.
            outstanding_quantity=requested_quantity,
            purchase_unit=purchase_unit,
        )

    @staticmethod
    @transaction.atomic
    def submit_requisition(*, requisition) -> PurchaseRequisition:
        """Hand the requisition to an approver."""
        if requisition.status != PurchaseRequisition.Status.DRAFT:
            raise ValidationError(
                f"Only a draft requisition may be submitted; this one is {requisition.status}."
            )
        if not PurchaseRequisitionLine.all_objects.filter(requisition=requisition).exists():
            raise ValidationError("A requisition with no lines cannot be submitted.")

        requisition.status = PurchaseRequisition.Status.SUBMITTED
        requisition.save(update_fields=["status", "updated_at"])
        return requisition

    @staticmethod
    @transaction.atomic
    def approve_requisition(*, requisition, approver) -> PurchaseRequisition:
        """Approve a requisition.

        The requester may not approve their own. An approval that the requester
        can grant themselves is not a control -- it is a checkbox, and it turns
        the whole approval chain into paperwork.
        """
        if approver is None:
            raise ValidationError("Requisition approval requires a named approver.")
        if requisition.requester_id == getattr(approver, "pk", None):
            raise ValidationError(
                "Requester cannot approve their own purchase requisition."
            )
        if requisition.status in {PurchaseRequisition.Status.DRAFT}:
            raise ValidationError(
                "A draft requisition must be submitted before it can be approved."
            )
        if requisition.status not in [PurchaseRequisition.Status.SUBMITTED, PurchaseRequisition.Status.UNDER_REVIEW]:
            raise ValidationError(f"Cannot approve requisition in status {requisition.status}")

        requisition.status = PurchaseRequisition.Status.APPROVED
        requisition.approved_by = approver
        requisition.approved_at = timezone.now()
        requisition.save()
        return requisition

    @staticmethod
    @transaction.atomic
    def create_rfq(*, tenant, title, lines_data, closing_date) -> RequestForQuotation:
        rfq_number = f"RFQ-{timezone.now().strftime('%Y%m%d')}-{RequestForQuotation.all_objects.filter(tenant=tenant).count() + 1:04d}"
        rfq = RequestForQuotation.all_objects.create(
            tenant=tenant,
            rfq_number=rfq_number,
            title=title,
            closing_date=closing_date,
            status="OPEN",
        )

        for line in lines_data:
            RFQLine.all_objects.create(
                tenant=tenant,
                rfq=rfq,
                sku=line["sku"],
                requested_quantity=line["requested_quantity"],
            )

        return rfq

    @staticmethod
    @transaction.atomic
    def award_quotation(*, rfq, winning_quotation, awarded_by) -> QuotationAward:
        award = QuotationAward.all_objects.create(
            tenant=rfq.tenant,
            rfq=rfq,
            winning_quotation=winning_quotation,
            awarded_by=awarded_by,
        )
        rfq.status = "AWARDED"
        rfq.save()

        winning_quotation.status = "ACCEPTED"
        winning_quotation.save()
        return award

    @staticmethod
    @transaction.atomic
    def create_purchase_order(*, tenant, supplier, ordering_branch, lines_data, created_by, currency="KES") -> PurchaseOrder:
        if supplier.status not in [Supplier.Status.APPROVED, Supplier.Status.ACTIVE]:
            raise ValidationError(f"Supplier {supplier.legal_name} is not approved for purchasing.")

        # Tenant/Branch/PO/Year/Sequence per the numbering convention. The
        # sequence component is random rather than count()+1: two POs raised in
        # the same instant would otherwise take the same number and the unique
        # constraint would fail one of them at random.
        year = timezone.now().year
        po_number = f"TIBA/{ordering_branch.code}/PO/{year}/{uuid.uuid4().hex[:6].upper()}"

        po = PurchaseOrder.all_objects.create(
            tenant=tenant,
            po_number=po_number,
            supplier=supplier,
            ordering_branch=ordering_branch,
            created_by=created_by,
            currency=currency,
            status=PurchaseOrder.Status.DRAFT,
        )

        total_gross = decimal.Decimal("0.00")
        for item in lines_data:
            qty = item["quantity"]
            unit_cost = item["unit_cost"]
            line_total = decimal.Decimal(qty) * decimal.Decimal(unit_cost)
            total_gross += line_total

            PurchaseOrderLine.all_objects.create(
                tenant=tenant,
                purchase_order=po,
                sku=item["sku"],
                ordered_quantity=qty,
                unit_cost=unit_cost,
                tax_rate=item.get("tax_rate", decimal.Decimal("0.00")),
                line_total=line_total,
            )

        po.total_gross = total_gross
        po.total_net = total_gross
        po.save()
        return po

    @staticmethod
    @transaction.atomic
    def create_po_from_requisition(*, tenant, supplier, requisition, ordering_branch,
                                   creator, po_number=None, order_date=None,
                                   expected_delivery_date=None, currency="KES") -> PurchaseOrder:
        """Raise a purchase order against an approved requisition.

        The requisition must be approved. Ordering from an unapproved demand
        document commits the organisation's money on the strength of a request
        nobody signed off, which is the whole reason the requisition exists.

        Supplier eligibility is checked here rather than at release, because a
        buyer who has already built a PO argues to keep it.
        """
        if requisition.status != PurchaseRequisition.Status.APPROVED:
            raise ValidationError(
                f"A purchase order requires an approved requisition; "
                f"{requisition.requisition_number} is {requisition.status}."
            )

        SupplierGovernanceService.assert_can_receive_purchase_order(
            supplier=supplier, on_date=order_date
        )

        lines_data = [
            {
                "sku": line.sku,
                "quantity": line.requested_quantity,
                "unit_cost": getattr(line, "estimated_unit_cost", decimal.Decimal("0.00"))
                or decimal.Decimal("0.00"),
            }
            for line in PurchaseRequisitionLine.all_objects.filter(requisition=requisition)
        ]
        if not lines_data:
            raise ValidationError("The requisition has no lines to order.")

        po = ProcurementService.create_purchase_order(
            tenant=tenant,
            supplier=supplier,
            ordering_branch=ordering_branch,
            lines_data=lines_data,
            created_by=creator,
            currency=currency,
        )

        if po_number:
            po.po_number = po_number
        if order_date:
            po.order_date = order_date
        if expected_delivery_date:
            po.expected_delivery_date = expected_delivery_date
        po.save()

        requisition.status = PurchaseRequisition.Status.CONVERTED
        requisition.save(update_fields=["status", "updated_at"])
        return po

    @staticmethod
    @transaction.atomic
    def approve_po(*, purchase_order, approver) -> PurchaseOrder:
        """Alias kept because approval is named for the document, not the verb."""
        return ProcurementService.approve_purchase_order(
            purchase_order=purchase_order, approver=approver
        )

    @staticmethod
    @transaction.atomic
    def send_po(*, purchase_order) -> PurchaseOrder:
        """Release the order to the supplier.

        Only an approved PO may be sent. Sending an unapproved one is placing
        an order nobody authorised.
        """
        if purchase_order.status != PurchaseOrder.Status.APPROVED:
            raise ValidationError(
                f"Only an approved purchase order may be sent; this one is "
                f"{purchase_order.status}."
            )
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["status", "updated_at"])
        return purchase_order

    @staticmethod
    @transaction.atomic
    def approve_purchase_order(*, purchase_order, approver) -> PurchaseOrder:
        if purchase_order.status != PurchaseOrder.Status.DRAFT:
            raise ValidationError(f"Cannot approve PO in status {purchase_order.status}")

        purchase_order.status = PurchaseOrder.Status.APPROVED
        purchase_order.approved_by = approver
        purchase_order.approved_at = timezone.now()
        purchase_order.save()
        return purchase_order

    @staticmethod
    @transaction.atomic
    def revise_purchase_order(*, purchase_order, actor, reason, updated_lines_data) -> PurchaseOrderRevision:
        if purchase_order.status not in [PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.RELEASED]:
            raise ValidationError("Revisions can only be performed on Approved or Released Purchase Orders.")

        rev_num = purchase_order.revision_number + 1
        revision = PurchaseOrderRevision.all_objects.create(
            tenant=purchase_order.tenant,
            purchase_order=purchase_order,
            revision_number=rev_num,
            actor=actor,
            reason_summary=reason,
            snapshot_data={"total_gross": str(purchase_order.total_gross)},
        )

        purchase_order.revision_number = rev_num
        purchase_order.status = PurchaseOrder.Status.SUBMITTED
        purchase_order.save()
        return revision
