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
from apps.procurement.services.supplier_governance_service import (
    PURCHASABLE_STATUSES,
    SupplierGovernanceService,
)


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
    def create_purchase_order(*, tenant, supplier, ordering_branch, lines_data, created_by=None,
                              currency="KES", requisition=None, po_number=None,
                              order_date=None, expected_delivery_date=None) -> PurchaseOrder:
        if supplier.status not in [Supplier.Status.APPROVED, Supplier.Status.ACTIVE]:
            raise ValidationError(f"Supplier {supplier.legal_name} is not approved for purchasing.")

        # Tenant/Branch/PO/Year/Sequence per the numbering convention. The
        # sequence component is random rather than count()+1: two POs raised in
        # the same instant would otherwise take the same number and the unique
        # constraint would fail one of them at random.
        year = timezone.now().year
        po_number = po_number or (
            f"TIBA/{ordering_branch.code}/PO/{year}/{uuid.uuid4().hex[:6].upper()}"
        )

        po = PurchaseOrder.all_objects.create(
            tenant=tenant,
            po_number=po_number,
            supplier=supplier,
            ordering_branch=ordering_branch,
            originating_requisition=requisition,
            # Both are required by the model. Defaulting them to today keeps a
            # PO raised without an explicit date valid rather than silently
            # unsaveable.
            order_date=order_date or timezone.localdate(),
            expected_delivery_date=expected_delivery_date or timezone.localdate(),
            currency=currency,
            status=PurchaseOrder.Status.DRAFT,
            created_by=created_by,
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
                unit_price=unit_cost,
                total_price=line_total,
                purchase_unit=item.get("purchase_unit", "pack"),
                requires_cold_chain=item.get("requires_cold_chain", False),
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
            requisition=requisition,
            po_number=po_number,
            order_date=order_date,
            expected_delivery_date=expected_delivery_date,
        )

        # The model's terminal ordered state. §8 calls this CONVERTED; the
        # schema calls it FULLY_ORDERED, and the schema is what exists.
        requisition.status = PurchaseRequisition.Status.FULLY_ORDERED
        requisition.save(update_fields=["status", "updated_at"])
        return po

    @staticmethod
    @transaction.atomic
    def create_priced_po_from_requisition(
        *,
        tenant,
        supplier,
        requisition,
        ordering_branch,
        creator,
        lines_data,
        po_number=None,
        order_date=None,
        expected_delivery_date=None,
        currency="KES",
    ) -> PurchaseOrder:
        if requisition.status != PurchaseRequisition.Status.APPROVED:
            raise ValidationError(
                f"A purchase order requires an approved requisition; "
                f"{requisition.requisition_number} is {requisition.status}."
            )
        SupplierGovernanceService.assert_can_receive_purchase_order(
            supplier=supplier,
            on_date=order_date,
            cold_chain=any(bool(item.get("requires_cold_chain")) for item in lines_data),
        )

        requisition_lines = {
            str(line.pk): line
            for line in PurchaseRequisitionLine.all_objects.select_for_update().filter(
                tenant=tenant,
                requisition=requisition,
            )
        }
        purchase_lines = []
        selected_lines = []
        for item in lines_data:
            requisition_line = requisition_lines.get(str(item["requisition_line"]))
            if requisition_line is None:
                raise ValidationError("A purchase-order line is outside the selected requisition.")
            quantity = int(item.get("quantity") or requisition_line.outstanding_quantity)
            if quantity <= 0 or quantity > requisition_line.outstanding_quantity:
                raise ValidationError(
                    f"Order quantity for {requisition_line.sku.sku_code} must be between "
                    f"1 and {requisition_line.outstanding_quantity}."
                )
            purchase_lines.append(
                {
                    "sku": requisition_line.sku,
                    "quantity": quantity,
                    "unit_cost": item["unit_cost"],
                    "purchase_unit": requisition_line.purchase_unit,
                    "requires_cold_chain": bool(item.get("requires_cold_chain", False)),
                }
            )
            selected_lines.append((requisition_line, quantity))

        if not purchase_lines:
            raise ValidationError("Select at least one requisition line to order.")

        purchase_order = ProcurementService.create_purchase_order(
            tenant=tenant,
            supplier=supplier,
            ordering_branch=ordering_branch,
            lines_data=purchase_lines,
            created_by=creator,
            currency=currency,
            requisition=requisition,
            po_number=po_number,
            order_date=order_date,
            expected_delivery_date=expected_delivery_date,
        )

        for requisition_line, quantity in selected_lines:
            requisition_line.approved_quantity = max(
                requisition_line.approved_quantity,
                requisition_line.requested_quantity,
            )
            requisition_line.outstanding_quantity -= quantity
            requisition_line.status = (
                PurchaseRequisitionLine.LineStatus.ORDERED
                if requisition_line.outstanding_quantity == 0
                else PurchaseRequisitionLine.LineStatus.APPROVED
            )
            requisition_line.save(
                update_fields=[
                    "approved_quantity",
                    "outstanding_quantity",
                    "status",
                    "updated_at",
                ]
            )

        remaining = PurchaseRequisitionLine.all_objects.filter(
            tenant=tenant,
            requisition=requisition,
            outstanding_quantity__gt=0,
        ).exists()
        requisition.status = (
            PurchaseRequisition.Status.PARTIALLY_ORDERED
            if remaining
            else PurchaseRequisition.Status.FULLY_ORDERED
        )
        requisition.save(update_fields=["status", "updated_at"])
        return purchase_order

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
        """Approve an order for release to the supplier.

        Re-checks the supplier. Eligibility was verified when the order was
        raised, but a supplier can be suspended between drafting and approval --
        for a compliance violation, a lapsed licence, a quality failure -- and
        approving on the strength of a check made days earlier commits the
        organisation to a counterparty it has since decided not to buy from.
        """
        supplier = purchase_order.supplier
        if supplier.status not in PURCHASABLE_STATUSES:
            raise ValidationError(
                f"Cannot approve PO for a supplier that is not APPROVED or ACTIVE; "
                f"{supplier.supplier_code} is {supplier.status}."
            )

        if purchase_order.status != PurchaseOrder.Status.DRAFT:
            raise ValidationError(f"Cannot approve PO in status {purchase_order.status}")
        if approver is None:
            raise ValidationError("Purchase-order approval requires a named approver.")
        if (
            purchase_order.created_by_id
            and str(purchase_order.created_by_id) == str(getattr(approver, "pk", None))
        ):
            # Matches approve_requisition. An approval the raiser can grant
            # themselves is not a control on a commercial commitment.
            raise ValidationError(
                "The person who raised a purchase order cannot approve it."
            )

        purchase_order.status = PurchaseOrder.Status.APPROVED
        purchase_order.approved_by = approver
        purchase_order.approved_at = timezone.now()
        purchase_order.save()
        return purchase_order

    @staticmethod
    @transaction.atomic
    def revise_purchase_order(*, purchase_order, actor, reason=None, change_reason=None,
                              updated_lines_data=None, **changed_fields) -> PurchaseOrderRevision:
        # Callers name it reason or change_reason; both mean why the released
        # order is being altered, which is the thing that must be recorded.
        reason = reason or change_reason
        if not str(reason or "").strip():
            raise ValidationError("A purchase-order revision requires a reason.")
        if purchase_order.status not in [PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.SENT]:
            raise ValidationError("Revisions can only be performed on Approved or Released Purchase Orders.")

        superseded_revision = purchase_order.revision_number
        rev_num = superseded_revision + 1
        revision = PurchaseOrderRevision.all_objects.create(
            tenant=purchase_order.tenant,
            purchase_order=purchase_order,
            # The version this record supersedes, because that is the version
            # its snapshot describes. Numbering it with the new revision would
            # attach the old state to the new version's number.
            revision_number=superseded_revision,
            actor=actor,
            change_reason=reason,
            # The full prior state, not just the total. A revision exists so
            # somebody can see what the order said before it changed, and a
            # single figure does not answer that.
            previous_snapshot={
                "po_number": purchase_order.po_number,
                "revision_number": purchase_order.revision_number,
                "status": purchase_order.status,
                "total_net": str(purchase_order.total_net),
                "total_tax": str(purchase_order.total_tax),
                "total_gross": str(purchase_order.total_gross),
                "expected_delivery_date": str(purchase_order.expected_delivery_date),
                "lines": [
                    {
                        "sku": str(line.sku_id),
                        "ordered_quantity": line.ordered_quantity,
                        "unit_price": str(line.unit_price),
                        "total_price": str(line.total_price),
                    }
                    for line in PurchaseOrderLine.all_objects.filter(
                        tenant_id=purchase_order.tenant_id,
                        purchase_order=purchase_order,
                    )
                ],
            },
        )

        # Apply the requested changes, but only to fields the order actually
        # has. An unknown key is a caller mistake, and silently ignoring it
        # leaves them believing a price or a date was revised when it was not.
        for field, value in changed_fields.items():
            if not hasattr(purchase_order, field):
                raise ValidationError(
                    f"{field} is not a field of a purchase order and cannot be revised."
                )
            setattr(purchase_order, field, value)

        purchase_order.revision_number = rev_num
        # Back to SUBMITTED, whatever it was before. A released order that has
        # had its price, quantity or delivery changed is a different commitment
        # from the one that was approved, and it needs approving again.
        purchase_order.status = PurchaseOrder.Status.SUBMITTED
        purchase_order.save()
        return revision
