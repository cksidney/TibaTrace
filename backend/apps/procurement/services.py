import decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderRevision,
    PurchaseRequisition,
    PurchaseRequisitionLine,
    ReceivedBatch,
    ReceivingInspection,
    Supplier,
    SupplierProductAgreement,
    SupplierQualification,
    SupplierReturn,
    SupplierReturnLine,
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
        if purchase_order.supplier.status not in [Supplier.Status.APPROVED, Supplier.Status.ACTIVE]:
            raise ValidationError("Cannot approve PO for a supplier that is not APPROVED or ACTIVE.")

        # Check mandatory supplier qualifications
        active_qualifications = SupplierQualification.all_objects.filter(
            tenant=purchase_order.tenant,
            supplier=purchase_order.supplier,
            verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED,
            expiry_date__gte=timezone.now().date(),
        ).values_list("qualification_type", flat=True)

        if SupplierQualification.QualificationType.BUSINESS_REGISTRATION not in active_qualifications:
            raise ValidationError("Supplier missing active BUSINESS_REGISTRATION qualification.")

        po_lines = PurchaseOrderLine.all_objects.filter(purchase_order=purchase_order)
        if any(line.requires_cold_chain for line in po_lines):
            if SupplierQualification.QualificationType.COLD_CHAIN_AUTHORIZATION not in active_qualifications:
                raise ValidationError("Supplier missing COLD_CHAIN_AUTHORIZATION for cold-chain products.")

        # If any SKU is a controlled drug, require CONTROLLED_DRUG_LICENCE
        for line in po_lines:
            if getattr(line.sku.manufactured_product.clinical_product, "controlled_classification", "NONE") != "NONE":
                if SupplierQualification.QualificationType.CONTROLLED_DRUG_LICENCE not in active_qualifications:
                    raise ValidationError("Supplier missing CONTROLLED_DRUG_LICENCE for controlled products.")

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

    @staticmethod
    @transaction.atomic
    def revise_purchase_order(*, purchase_order, actor, change_reason, **changes):
        if purchase_order.status not in [PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.SENT, PurchaseOrder.Status.ACKNOWLEDGED]:
            raise ValidationError("Can only revise APPROVED, SENT, or ACKNOWLEDGED Purchase Orders.")

        # Serialize snapshot
        po_dict = {
            "po_number": purchase_order.po_number,
            "supplier_id": str(purchase_order.supplier_id),
            "order_date": str(purchase_order.order_date),
            "expected_delivery_date": str(purchase_order.expected_delivery_date),
            "currency": purchase_order.currency,
            "total_net": str(purchase_order.total_net),
            "status": purchase_order.status,
            "lines": [
                {
                    "sku_id": str(line_item.sku_id),
                    "ordered_quantity": line_item.ordered_quantity,
                    "unit_price": str(line_item.unit_price)
                } for line_item in PurchaseOrderLine.all_objects.filter(purchase_order=purchase_order)
            ]
        }
        
        PurchaseOrderRevision.objects.create(
            tenant=purchase_order.tenant,
            purchase_order=purchase_order,
            revision_number=purchase_order.revision_number,
            change_reason=change_reason,
            previous_snapshot=po_dict,
            actor=actor
        )

        for key, value in changes.items():
            if hasattr(purchase_order, key):
                setattr(purchase_order, key, value)
        
        purchase_order.revision_number += 1
        purchase_order.status = PurchaseOrder.Status.SUBMITTED
        purchase_order.approved_at = None
        purchase_order.approved_by = None
        purchase_order.save()

        emit_event(
            tenant_id=str(purchase_order.tenant.pk),
            aggregate_type="PurchaseOrder",
            aggregate_id=str(purchase_order.pk),
            event_type="PurchaseOrderRevised",
            payload={"po_number": purchase_order.po_number, "revision": purchase_order.revision_number, "reason": change_reason},
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
    def receive_line(*, goods_receipt, po_line, delivered_quantity, accepted_quantity=0, quarantined_quantity=0, rejected_quantity=0, discrepancy_reason="", idempotency_key=""):
        if idempotency_key:
            existing_line = GoodsReceiptLine.all_objects.filter(tenant=goods_receipt.tenant, idempotency_key=idempotency_key).first()
            if existing_line:
                return existing_line

        if (accepted_quantity + quarantined_quantity + rejected_quantity) > delivered_quantity:
            raise ValidationError("Accepted + Quarantined + Rejected quantities cannot exceed delivered quantity.")

        # Acquire a row-level lock to prevent concurrent over-receipts
        locked_po_line = PurchaseOrderLine.objects.select_for_update().get(pk=po_line.pk)

        if locked_po_line.received_quantity + delivered_quantity > locked_po_line.ordered_quantity:
            raise ValidationError("Total received quantity cannot exceed ordered quantity.")

        grn_line = GoodsReceiptLine.objects.create(
            tenant=goods_receipt.tenant,
            goods_receipt=goods_receipt,
            po_line=locked_po_line,
            sku=locked_po_line.sku,
            delivered_quantity=delivered_quantity,
            accepted_quantity=accepted_quantity,
            quarantined_quantity=quarantined_quantity,
            rejected_quantity=rejected_quantity,
            discrepancy_reason=discrepancy_reason,
            idempotency_key=idempotency_key,
        )

        locked_po_line.received_quantity += delivered_quantity
        locked_po_line.rejected_quantity += rejected_quantity
        locked_po_line.save()

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
        if manufacture_date and manufacture_date >= expiry_date:
            raise ValidationError("Manufacture date must precede expiry date.")
        
        if expiry_date <= timezone.now().date():
            raise ValidationError("Cannot receive expired batch.")

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
        if not actor.has_capability("procurement.quality_release", tenant_id=str(batch.tenant.pk)):
            raise ValidationError("Actor lacks quality-release authority.")

        if batch.quality_status in [ReceivedBatch.QualityStatus.REJECTED, ReceivedBatch.QualityStatus.DESTROYED, ReceivedBatch.QualityStatus.RETURNED]:
            raise ValidationError("Cannot release rejected or terminal batches.")

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

    @staticmethod
    @transaction.atomic
    def add_return_line(*, supplier_return, sku, quantity, batch=None):
        if supplier_return.status != SupplierReturn.Status.REQUESTED:
            raise ValidationError("Can only add lines to requested return.")
        
        # Verify quantity does not exceed rejected/quarantined from GRN
        grn_lines = GoodsReceiptLine.all_objects.filter(goods_receipt=supplier_return.goods_receipt, sku=sku)
        total_eligible = sum(line.rejected_quantity + line.quarantined_quantity for line in grn_lines)
        if quantity > total_eligible:
            raise ValidationError("Return quantity exceeds eligible rejected/quarantined quantity.")

        return SupplierReturnLine.objects.create(
            tenant=supplier_return.tenant,
            supplier_return=supplier_return,
            sku=sku,
            batch=batch,
            quantity=quantity
        )


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
