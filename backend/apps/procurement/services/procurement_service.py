from __future__ import annotations

import decimal

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


class ProcurementService:
    """
    Authoritative domain service for Requisitions, RFQs, Quotation Awards,
    PO Creation, Approval, and Immutable Revisions.
    """

    @staticmethod
    @transaction.atomic
    def create_requisition(*, tenant, requesting_branch, requester, lines_data, priority="NORMAL", reason="") -> PurchaseRequisition:
        req_number = f"REQ-{timezone.now().strftime('%Y%m%d')}-{PurchaseRequisition.all_objects.filter(tenant=tenant).count() + 1:05d}"
        requisition = PurchaseRequisition.all_objects.create(
            tenant=tenant,
            requisition_number=req_number,
            requesting_branch=requesting_branch,
            requester=requester,
            priority=priority,
            reason=reason,
            status=PurchaseRequisition.Status.SUBMITTED,
        )

        for item in lines_data:
            PurchaseRequisitionLine.all_objects.create(
                tenant=tenant,
                requisition=requisition,
                sku=item["sku"],
                requested_quantity=item["requested_quantity"],
                estimated_unit_cost=item.get("estimated_unit_cost", decimal.Decimal("0.00")),
                reason=item.get("reason", ""),
            )

        return requisition

    @staticmethod
    @transaction.atomic
    def approve_requisition(*, requisition, approver) -> PurchaseRequisition:
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

        seq = PurchaseOrder.all_objects.filter(tenant=tenant).count() + 1
        year = timezone.now().year
        po_number = f"TIBA/{ordering_branch.code}/PO/{year}/{seq:06d}"

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
