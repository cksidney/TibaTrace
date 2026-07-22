import decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    PurchaseRequisitionLine,
    ReceivedBatch,
    ReceivingInspection,
    Supplier,
    SupplierProductAgreement,
    SupplierQualification,
    SupplierReturn,
    ThreeWayMatch,
)
from apps.workflows.service import emit_event


class SupplierGovernanceService:

    @staticmethod
    @transaction.atomic
    def create_supplier(*, tenant, supplier_code, legal_name, trading_name="", registration_number="", tax_identifier="", country="Kenya", payment_terms="NET30", default_currency="KES", actor=None):
        supplier = Supplier.objects.create(
            tenant=tenant,
            supplier_code=supplier_code,
            legal_name=legal_name,
            trading_name=trading_name,
            registration_number=registration_number,
            tax_identifier=tax_identifier,
            country=country,
            payment_terms=payment_terms,
            default_currency=default_currency,
            status=Supplier.Status.PROSPECTIVE,
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="Supplier",
            aggregate_id=str(supplier.pk),
            event_type="SupplierCreated",
            payload={"supplier_code": supplier.supplier_code, "legal_name": supplier.legal_name, "actor_id": str(actor.pk) if actor else None},
        )
        return supplier

    @staticmethod
    @transaction.atomic
    def approve_supplier(*, supplier, approver, reason="Approved"):
        supplier.status = Supplier.Status.APPROVED
        supplier.approved_at = timezone.now()
        supplier.approved_by = approver
        supplier.save()

        emit_event(
            tenant_id=str(supplier.tenant.pk),
            aggregate_type="Supplier",
            aggregate_id=str(supplier.pk),
            event_type="SupplierApproved",
            payload={"supplier_code": supplier.supplier_code, "approver_id": str(approver.pk), "reason": reason},
        )
        return supplier

    @staticmethod
    @transaction.atomic
    def suspend_supplier(*, supplier, reason):
        supplier.status = Supplier.Status.SUSPENDED
        supplier.suspension_reason = reason
        supplier.save()

        emit_event(
            tenant_id=str(supplier.tenant.pk),
            aggregate_type="Supplier",
            aggregate_id=str(supplier.pk),
            event_type="SupplierSuspended",
            payload={"supplier_code": supplier.supplier_code, "reason": reason},
        )
        return supplier


class SupplierQualificationService:

    @staticmethod
    @transaction.atomic
    def verify_qualification(*, qualification, verifier):
        qualification.verification_status = SupplierQualification.QualificationVerificationStatus.VERIFIED
        qualification.verified_at = timezone.now()
        qualification.verified_by = verifier
        qualification.save()

        emit_event(
            tenant_id=str(qualification.tenant.pk),
            aggregate_type="SupplierQualification",
            aggregate_id=str(qualification.pk),
            event_type="SupplierQualificationVerified",
            payload={"licence_number": qualification.licence_number, "verifier_id": str(verifier.pk)},
        )
        return qualification


class SupplierProductAgreementService:

    @staticmethod
    @transaction.atomic
    def register_agreement(*, tenant, supplier, sku, agreed_unit_price, purchase_unit="pack", currency="KES", minimum_order_quantity=1, lead_time_days=3, is_preferred=False):
        if supplier.status not in [Supplier.Status.APPROVED, Supplier.Status.ACTIVE]:
            raise ValidationError("Cannot register product agreement for non-approved supplier.")

        agreement, _ = SupplierProductAgreement.objects.get_or_create(
            tenant=tenant,
            supplier=supplier,
            sku=sku,
            defaults={
                "agreed_unit_price": agreed_unit_price,
                "purchase_unit": purchase_unit,
                "currency": currency,
                "minimum_order_quantity": minimum_order_quantity,
                "lead_time_days": lead_time_days,
                "is_preferred": is_preferred,
                "status": SupplierProductAgreement.Status.ACTIVE,
            },
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="SupplierProductAgreement",
            aggregate_id=str(agreement.pk),
            event_type="SupplierProductAgreementCreated",
            payload={"supplier_code": supplier.supplier_code, "sku_code": sku.sku_code, "agreed_unit_price": str(agreed_unit_price)},
        )
        return agreement


class PurchaseRequisitionService:

    @staticmethod
    @transaction.atomic
    def create_requisition(*, tenant, requisition_number, requesting_branch, requester, requested_delivery_date, priority="NORMAL", justification=""):
        req = PurchaseRequisition.objects.create(
            tenant=tenant,
            requisition_number=requisition_number,
            requesting_branch=requesting_branch,
            requester=requester,
            requested_delivery_date=requested_delivery_date,
            priority=priority,
            justification=justification,
            status=PurchaseRequisition.Status.DRAFT,
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="PurchaseRequisition",
            aggregate_id=str(req.pk),
            event_type="PurchaseRequisitionCreated",
            payload={"requisition_number": req.requisition_number, "requester_id": str(requester.pk)},
        )
        return req

    @staticmethod
    @transaction.atomic
    def add_line(*, requisition, sku, requested_quantity, purchase_unit="pack"):
        if requisition.status != PurchaseRequisition.Status.DRAFT:
            raise ValidationError("Cannot modify lines of a non-draft requisition.")
        return PurchaseRequisitionLine.objects.create(
            tenant=requisition.tenant,
            requisition=requisition,
            sku=sku,
            requested_quantity=requested_quantity,
            approved_quantity=requested_quantity,
            outstanding_quantity=requested_quantity,
            purchase_unit=purchase_unit,
            status=PurchaseRequisitionLine.LineStatus.PENDING,
        )

    @staticmethod
    @transaction.atomic
    def approve_requisition(*, requisition, approver):
        if requisition.requester == approver:
            raise ValidationError("Requester cannot approve their own purchase requisition (Segregation of Duties).")

        requisition.status = PurchaseRequisition.Status.APPROVED
        requisition.approved_at = timezone.now()
        requisition.approved_by = approver
        requisition.save()

        emit_event(
            tenant_id=str(requisition.tenant.pk),
            aggregate_type="PurchaseRequisition",
            aggregate_id=str(requisition.pk),
            event_type="PurchaseRequisitionApproved",
            payload={"requisition_number": requisition.requisition_number, "approver_id": str(approver.pk)},
        )
        return requisition


class PurchaseOrderService:

    @staticmethod
    @transaction.atomic
    def create_po_from_requisition(*, tenant, po_number, supplier, requisition, ordering_branch, order_date, expected_delivery_date, creator):
        if supplier.status not in [Supplier.Status.APPROVED, Supplier.Status.ACTIVE]:
            raise ValidationError("Cannot create PO for non-approved supplier.")

        po = PurchaseOrder.objects.create(
            tenant=tenant,
            po_number=po_number,
            supplier=supplier,
            originating_requisition=requisition,
            ordering_branch=ordering_branch,
            order_date=order_date,
            expected_delivery_date=expected_delivery_date,
            currency=supplier.default_currency,
            status=PurchaseOrder.Status.DRAFT,
        )

        total_net = decimal.Decimal("0.00")
        for req_line in PurchaseRequisitionLine.all_objects.filter(requisition=requisition):
            agreement = SupplierProductAgreement.objects.filter(tenant=tenant, supplier=supplier, sku=req_line.sku).first()
            unit_price = agreement.agreed_unit_price if agreement else decimal.Decimal("100.00")
            line_total = unit_price * req_line.requested_quantity

            PurchaseOrderLine.objects.create(
                tenant=tenant,
                purchase_order=po,
                sku=req_line.sku,
                supplier_agreement=agreement,
                ordered_quantity=req_line.requested_quantity,
                unit_price=unit_price,
                total_price=line_total,
                purchase_unit=req_line.purchase_unit,
            )
            total_net += line_total

        po.total_net = total_net
        po.total_gross = total_net
        po.save()

        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="PurchaseOrder",
            aggregate_id=str(po.pk),
            event_type="PurchaseOrderCreated",
            payload={"po_number": po.po_number, "supplier_code": supplier.supplier_code, "creator_id": str(creator.pk)},
        )
        return po

    @staticmethod
    @transaction.atomic
    def approve_po(*, purchase_order, approver):
        purchase_order.status = PurchaseOrder.Status.APPROVED
        purchase_order.approved_at = timezone.now()
        purchase_order.approved_by = approver
        purchase_order.save()

        emit_event(
            tenant_id=str(purchase_order.tenant.pk),
            aggregate_type="PurchaseOrder",
            aggregate_id=str(purchase_order.pk),
            event_type="PurchaseOrderApproved",
            payload={"po_number": purchase_order.po_number, "approver_id": str(approver.pk)},
        )
        return purchase_order

    @staticmethod
    @transaction.atomic
    def send_po(*, purchase_order):
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save()

        emit_event(
            tenant_id=str(purchase_order.tenant.pk),
            aggregate_type="PurchaseOrder",
            aggregate_id=str(purchase_order.pk),
            event_type="PurchaseOrderSent",
            payload={"po_number": purchase_order.po_number},
        )
        return purchase_order


class GoodsReceivingService:

    @staticmethod
    @transaction.atomic
    def start_goods_receipt(*, tenant, grn_number, purchase_order, receiving_branch, receiver, delivery_note_number, arrival_time=None):
        if purchase_order.status not in [PurchaseOrder.Status.SENT, PurchaseOrder.Status.ACKNOWLEDGED, PurchaseOrder.Status.APPROVED]:
            raise ValidationError("Cannot receive against unapproved or non-sent PO.")

        grn = GoodsReceipt.objects.create(
            tenant=tenant,
            grn_number=grn_number,
            purchase_order=purchase_order,
            supplier=purchase_order.supplier,
            receiving_branch=receiving_branch,
            received_by=receiver,
            delivery_note_number=delivery_note_number,
            arrival_time=arrival_time or timezone.now(),
            status=GoodsReceipt.Status.RECEIVING,
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="GoodsReceipt",
            aggregate_id=str(grn.pk),
            event_type="GoodsReceiptStarted",
            payload={"grn_number": grn.grn_number, "po_number": purchase_order.po_number, "receiver_id": str(receiver.pk)},
        )
        return grn

    @staticmethod
    @transaction.atomic
    def receive_line(*, goods_receipt, po_line, delivered_quantity, accepted_quantity=0, quarantined_quantity=0, rejected_quantity=0, discrepancy_reason=""):
        if (accepted_quantity + quarantined_quantity + rejected_quantity) > delivered_quantity:
            raise ValidationError("Accepted + Quarantined + Rejected quantities cannot exceed delivered quantity.")

        grn_line = GoodsReceiptLine.objects.create(
            tenant=goods_receipt.tenant,
            goods_receipt=goods_receipt,
            po_line=po_line,
            sku=po_line.sku,
            delivered_quantity=delivered_quantity,
            accepted_quantity=accepted_quantity,
            quarantined_quantity=quarantined_quantity,
            rejected_quantity=rejected_quantity,
            discrepancy_reason=discrepancy_reason,
        )

        po_line.received_quantity += delivered_quantity
        po_line.rejected_quantity += rejected_quantity
        po_line.save()

        return grn_line

    @staticmethod
    @transaction.atomic
    def close_goods_receipt(*, goods_receipt):
        goods_receipt.status = GoodsReceipt.Status.ACCEPTED
        goods_receipt.save()

        # Check PO status
        po = goods_receipt.purchase_order
        po_lines = PurchaseOrderLine.all_objects.filter(purchase_order=po)
        total_ordered = sum(line_item.ordered_quantity for line_item in po_lines)
        total_received = sum(line_item.received_quantity for line_item in po_lines)

        if total_received >= total_ordered:
            po.status = PurchaseOrder.Status.FULLY_RECEIVED
        else:
            po.status = PurchaseOrder.Status.PARTIALLY_RECEIVED
        po.save()

        emit_event(
            tenant_id=str(goods_receipt.tenant.pk),
            aggregate_type="GoodsReceipt",
            aggregate_id=str(goods_receipt.pk),
            event_type="GoodsReceiptClosed",
            payload={"grn_number": goods_receipt.grn_number, "status": goods_receipt.status},
        )
        return goods_receipt


class BatchReceivingService:

    @staticmethod
    @transaction.atomic
    def capture_batch(*, grn_line, manufacturer_batch_number, expiry_date, received_quantity, manufacture_date=None, temperature_excursion=False):
        batch = ReceivedBatch.objects.create(
            tenant=grn_line.tenant,
            grn_line=grn_line,
            sku=grn_line.sku,
            manufacturer_batch_number=manufacturer_batch_number,
            manufacture_date=manufacture_date,
            expiry_date=expiry_date,
            received_quantity=received_quantity,
            quarantined_quantity=received_quantity if temperature_excursion else 0,
            accepted_quantity=0 if temperature_excursion else received_quantity,
            quality_status=ReceivedBatch.QualityStatus.QUARANTINED if temperature_excursion else ReceivedBatch.QualityStatus.PENDING_INSPECTION,
            temperature_excursion=temperature_excursion,
        )
        emit_event(
            tenant_id=str(grn_line.tenant.pk),
            aggregate_type="ReceivedBatch",
            aggregate_id=str(batch.pk),
            event_type="BatchCaptured",
            payload={"batch_number": batch.manufacturer_batch_number, "sku_code": grn_line.sku.sku_code, "expiry_date": str(expiry_date)},
        )
        return batch

    @staticmethod
    @transaction.atomic
    def release_batch(*, batch, actor, reason="Inspection passed"):
        batch.quality_status = ReceivedBatch.QualityStatus.RELEASED
        batch.accepted_quantity = batch.received_quantity
        batch.quarantined_quantity = 0
        batch.save()

        emit_event(
            tenant_id=str(batch.tenant.pk),
            aggregate_type="ReceivedBatch",
            aggregate_id=str(batch.pk),
            event_type="BatchReleased",
            payload={"batch_number": batch.manufacturer_batch_number, "actor_id": str(actor.pk), "reason": reason},
        )
        return batch


class ReceivingInspectionService:

    @staticmethod
    @transaction.atomic
    def record_inspection(*, goods_receipt, inspector, decision, reason):
        inspection = ReceivingInspection.objects.create(
            tenant=goods_receipt.tenant,
            goods_receipt=goods_receipt,
            inspector=inspector,
            decision=decision,
            reason=reason,
        )
        return inspection


class SupplierReturnService:

    @staticmethod
    @transaction.atomic
    def request_return(*, tenant, return_number, goods_receipt, reason):
        ret = SupplierReturn.objects.create(
            tenant=tenant,
            return_number=return_number,
            goods_receipt=goods_receipt,
            supplier=goods_receipt.supplier,
            reason=reason,
            status=SupplierReturn.Status.REQUESTED,
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="SupplierReturn",
            aggregate_id=str(ret.pk),
            event_type="SupplierReturnRequested",
            payload={"return_number": ret.return_number, "reason": reason},
        )
        return ret


class ProcurementMatchingService:

    @staticmethod
    @transaction.atomic
    def reconcile_three_way_match(*, tenant, purchase_order, goods_receipt, invoice_reference=""):
        match, _ = ThreeWayMatch.objects.get_or_create(
            tenant=tenant,
            purchase_order=purchase_order,
            goods_receipt=goods_receipt,
            defaults={"invoice_reference": invoice_reference, "matching_status": ThreeWayMatch.MatchingStatus.MATCHED},
        )
        return match
