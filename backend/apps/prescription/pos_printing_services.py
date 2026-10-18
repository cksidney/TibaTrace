"""Authoritative POS document snapshots and print-job lifecycle services."""
from __future__ import annotations

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.money import format_money
from apps.prescription.models import DispensingLine
from apps.prescription.pos_printing_models import PosPrintDocument, PosPrintJob
from apps.prescription.services.clinical_dispensing import _require_capability
from apps.workflows.service import emit_event


def _hash_snapshot(snapshot):
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PosPrintDocumentService:
    @classmethod
    @transaction.atomic
    def issue_label(cls, *, label, actor, device_id):
        from apps.pos_shift.models import PosRegister
        _require_capability(actor, label.tenant_id, "pos.label.print")
        if not PosRegister.all_objects.filter(tenant_id=label.tenant_id, location_id=label.episode.branch_id,
                                             device_id=device_id).exists():
            raise ValidationError("Label destination must be a registered device in the dispensing branch.")
        number = f"{label.document_number}-{label.dispensing_line_id.hex[:8]}"
        existing = PosPrintDocument.all_objects.filter(tenant_id=label.tenant_id, label=label).first()
        if existing:
            job = PosPrintJob.all_objects.filter(tenant_id=label.tenant_id, document=existing, copy_classification="ORIGINAL").first()
            if job and job.device_id != device_id:
                raise ValidationError("The original label belongs to another till; use a governed reprint.")
            return existing, job
        snapshot = {"document_type": "MEDICINE_LABEL", "document_number": number, "label": label.content,
                    "issued_at": label.generated_at.isoformat(), "barcode_payload": label.barcode_payload}
        document = PosPrintDocument.all_objects.create(tenant_id=label.tenant_id, document_type="MEDICINE_LABEL",
            document_number=number, snapshot=snapshot, document_hash=_hash_snapshot(snapshot),
            episode=label.episode, label=label, created_by=actor)
        job = PosPrintJob.all_objects.create(tenant_id=label.tenant_id, document=document, branch=label.episode.branch,
            device_id=device_id, requested_by=actor, transport="WINDOWS_SPOOLER", idempotency_key=f"label-original:{label.pk}")
        return document, job

    @staticmethod
    def _receipt_snapshot(*, episode, settlement):
        tender = settlement.payment_tender
        intent = tender.payment_intent
        lines = list(
            DispensingLine.all_objects.filter(episode=episode)
            .select_related("supplied_sku", "prescribed_sku")
            .order_by("created_at")
        )
        patient_name = " ".join(
            value for value in [episode.patient.first_name, episode.patient.last_name] if value
        ).strip()
        return {
            "document_type": PosPrintDocument.DocumentType.PRESCRIPTION_RECEIPT,
            "document_number": f"RCP-{episode.dispensing_number}-{settlement.id.hex[:8].upper()}",
            "issued_at": settlement.settled_at.isoformat(),
            "tenant_id": str(episode.tenant_id),
            "branch_id": str(episode.branch_id),
            "episode_id": str(episode.id),
            "dispensing_number": episode.dispensing_number,
            "patient": {
                "id": str(episode.patient_id),
                "name": patient_name,
                "number": getattr(episode.patient, "patient_number", ""),
            },
            "prescription_number": getattr(episode.prescription, "prescription_number", ""),
            "lines": [
                {
                    "line_id": str(line.id),
                    "medicine": getattr(line.supplied_sku or line.prescribed_sku, "display_name", ""),
                    "quantity": str(line.quantity_authorized),
                    "unit": line.unit,
                    "batch_number": line.batch_number_snapshot,
                }
                for line in lines
            ],
            "payment": {
                "settlement_id": str(settlement.id),
                "reference": settlement.provider_reference or settlement.settlement_reference,
                "tender_type": tender.tender_type,
                "amount_due": format_money(intent.amount_due),
                "amount_settled": format_money(intent.effective_settled),
                "settled_amount": format_money(settlement.amount),
                "change_due": format_money(tender.change_due or 0),
                "currency": settlement.currency,
            },
            "register_session_id": str(tender.register_session_id or ""),
            "operator_shift_id": str(tender.operator_shift_id or ""),
        }

    @classmethod
    @transaction.atomic
    def issue_retail_receipt(
        cls,
        *,
        transaction_record,
        receipt,
        actor,
        printer="",
        transport=PosPrintJob.Transport.SIMULATOR,
    ):
        """Queue an immutable retail receipt without coupling it to dispensing."""
        if receipt.tenant_id != transaction_record.tenant_id or receipt.transaction_id != transaction_record.pk:
            raise ValidationError("Retail receipt does not belong to this transaction.")
        if transaction_record.state != "COMPLETED":
            raise ValidationError("A retail receipt may be queued only after cash settlement completed.")

        existing = PosPrintDocument.all_objects.filter(
            tenant_id=receipt.tenant_id,
            document_number=receipt.receipt_number,
            document_type=PosPrintDocument.DocumentType.RETAIL_RECEIPT,
        ).first()
        if existing:
            job = PosPrintJob.all_objects.filter(
                tenant_id=receipt.tenant_id,
                document=existing,
                copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
            ).first()
            return existing, job, True

        snapshot = {
            "document_type": PosPrintDocument.DocumentType.RETAIL_RECEIPT,
            "document_number": receipt.receipt_number,
            "issued_at": receipt.settled_at.isoformat(),
            "tenant_id": str(receipt.tenant_id),
            "branch_id": str(transaction_record.branch_id),
            "transaction_id": str(transaction_record.pk),
            "transaction_number": transaction_record.transaction_number,
            "register_session_id": str(transaction_record.register_session_id),
            "lines": receipt.lines_snapshot,
            "totals": receipt.totals_snapshot,
            "payment": {
                "tender_type": receipt.tender_type,
                "tenders": receipt.totals_snapshot.get("tenders", []),
                "amount": str(receipt.amount),
                "cash_received": str(receipt.cash_received),
                "change_due": str(receipt.change_due),
                "currency": receipt.currency,
            },
            "disclaimer": "Internal sales receipt — not a fiscal/eTIMS receipt.",
        }
        document = PosPrintDocument.all_objects.create(
            tenant_id=receipt.tenant_id,
            document_type=PosPrintDocument.DocumentType.RETAIL_RECEIPT,
            document_number=receipt.receipt_number,
            snapshot=snapshot,
            document_hash=_hash_snapshot(snapshot),
            register_session=transaction_record.register_session,
            created_by=actor,
        )
        job = PosPrintJob.all_objects.create(
            tenant_id=receipt.tenant_id,
            document=document,
            branch=transaction_record.branch,
            device_id=transaction_record.device_id,
            printer=printer,
            transport=transport,
            copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
            copy_number=1,
            requested_by=actor,
            idempotency_key=f"receipt-original:{receipt.pk}",
        )
        emit_event(
            tenant_id=str(receipt.tenant_id),
            aggregate_type="PosPrintDocument",
            aggregate_id=str(document.pk),
            event_type="POS_RETAIL_RECEIPT_QUEUED",
            payload={
                "document_number": document.document_number,
                "print_job_id": str(job.pk),
                "transaction_id": str(transaction_record.pk),
            },
        )
        return document, job, False

    @classmethod
    @transaction.atomic
    def issue_retail_refund(cls, *, receipt, actor, printer="", transport=PosPrintJob.Transport.SIMULATOR):
        """A refund receipt is printable evidence, never an instruction to refund twice."""
        if receipt.refund_request.status != "COMPLETED":
            raise ValidationError("A retail refund receipt requires completed cash execution.")
        existing = PosPrintDocument.all_objects.filter(tenant_id=receipt.tenant_id, document_number=receipt.refund_number).first()
        if existing:
            job = PosPrintJob.all_objects.filter(tenant_id=receipt.tenant_id, document=existing, copy_classification="ORIGINAL").first()
            return existing, job, True
        snapshot = {"document_type": "RETAIL_REFUND", "document_number": receipt.refund_number,
            "original_receipt_number": receipt.original_receipt.receipt_number, "issued_at": receipt.completed_at.isoformat(),
            "tenant_id": str(receipt.tenant_id), "branch_id": str(receipt.register.location_id),
            "transaction_id": str(receipt.original_receipt.transaction_id), "register_session_id": str(receipt.register_session_id),
            "lines": receipt.lines_snapshot, "payment": {"tender_type": "SPLIT" if len(receipt.payment_plan) > 1 else (receipt.payment_plan[0]["tender_type"] if receipt.payment_plan else "CASH"), "refund_amount": str(receipt.amount), "cash_amount": str(receipt.cash_amount), "tenders": receipt.payment_plan, "currency": receipt.currency},
            "disclaimer": "Internal refund receipt — not a fiscal/eTIMS credit note. Returned goods remain held pending quality disposition."}
        document = PosPrintDocument.all_objects.create(tenant_id=receipt.tenant_id, document_type="RETAIL_REFUND",
            document_number=receipt.refund_number, snapshot=snapshot, document_hash=_hash_snapshot(snapshot),
            register_session=receipt.register_session, created_by=actor)
        job = PosPrintJob.all_objects.create(tenant_id=receipt.tenant_id, document=document, branch=receipt.register.location,
            device_id=receipt.device_id, printer=printer, transport=transport, copy_classification="ORIGINAL", copy_number=1,
            requested_by=actor, idempotency_key=f"refund-original:{receipt.pk}")
        return document, job, False

    @classmethod
    @transaction.atomic
    def issue_receipt_for_settlement(cls, *, episode, settlement, actor, printer="", transport=PosPrintJob.Transport.SIMULATOR):
        episode = episode.__class__.all_objects.select_for_update().select_related(
            "tenant", "patient", "prescription", "branch"
        ).get(pk=episode.pk, tenant_id=episode.tenant_id)
        settlement = settlement.__class__.all_objects.select_related(
            "payment_tender__payment_intent", "payment_tender__register_session"
        ).get(pk=settlement.pk, tenant_id=episode.tenant_id)
        tender = settlement.payment_tender
        if tender.payment_intent.dispensing_episode_id != episode.id:
            raise ValidationError("Settlement does not belong to this dispensing episode.")
        if episode.payment_state != "PAID" or episode.status != "PAID":
            raise ValidationError("A receipt may be issued only after authoritative settlement completed.")
        if episode.payment_register_session_id and tender.register_session_id != episode.payment_register_session_id:
            raise ValidationError("Settlement register session does not match the settled episode.")

        existing = PosPrintDocument.all_objects.filter(
            settlement=settlement,
            document_type=PosPrintDocument.DocumentType.PRESCRIPTION_RECEIPT,
        ).first()
        if existing:
            job = PosPrintJob.all_objects.filter(
                tenant=episode.tenant,
                document=existing,
                copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
            ).first()
            return existing, job, True

        snapshot = cls._receipt_snapshot(episode=episode, settlement=settlement)
        document = PosPrintDocument.all_objects.create(
            tenant=episode.tenant,
            document_type=PosPrintDocument.DocumentType.PRESCRIPTION_RECEIPT,
            document_number=snapshot["document_number"],
            snapshot=snapshot,
            document_hash=_hash_snapshot(snapshot),
            episode=episode,
            settlement=settlement,
            register_session=tender.register_session,
            created_by=actor,
        )
        job = PosPrintJob.all_objects.create(
            tenant=episode.tenant,
            document=document,
            branch=episode.branch,
            device_id=episode.payment_device_id,
            printer=printer,
            transport=transport,
            copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
            copy_number=1,
            requested_by=actor,
            idempotency_key=f"receipt-original:{settlement.id}",
        )
        emit_event(
            tenant_id=str(episode.tenant_id),
            aggregate_type="PosPrintDocument",
            aggregate_id=str(document.id),
            event_type="POS_RECEIPT_QUEUED",
            payload={
                "episode_id": str(episode.id),
                "settlement_id": str(settlement.id),
                "document_number": document.document_number,
                "print_job_id": str(job.id),
            },
        )
        return document, job, False

    @staticmethod
    def receipt_status(*, settlement):
        document = PosPrintDocument.all_objects.filter(
            settlement=settlement,
            document_type=PosPrintDocument.DocumentType.PRESCRIPTION_RECEIPT,
        ).first()
        if not document:
            return None
        job = PosPrintJob.all_objects.filter(
            tenant=settlement.tenant,
            document=document,
            copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
        ).first()
        return {
            "document_number": document.document_number,
            "document_id": str(document.id),
            "print_job_id": str(job.id) if job else "",
            "status": job.status if job else "QUEUED",
        }


class PosPrintJobService:
    @classmethod
    @transaction.atomic
    def configure_transport(cls, *, job, actor, transport, printer, device_id):
        cls._require_print_capability(actor, job, "pos.document.print")
        job = PosPrintJob.all_objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if not device_id or job.device_id != device_id:
            raise ValidationError("Print job belongs to a different till installation.")
        if job.status not in {PosPrintJob.Status.QUEUED, PosPrintJob.Status.RENDERED}:
            raise ValidationError("Only an unsent print job can change printer transport.")
        if transport != PosPrintJob.Transport.WINDOWS_SPOOLER or not str(printer or "").strip():
            raise ValidationError("Select an installed Windows printer; other physical transports are not configured.")
        job.transport = transport
        job.printer = str(printer).strip()[:128]
        job.save(update_fields=["transport", "printer", "updated_at"])
        emit_event(tenant_id=str(job.tenant_id), aggregate_type="PosPrintJob", aggregate_id=str(job.pk),
            event_type="POS_PRINT_TRANSPORT_SELECTED", payload={"transport": transport, "printer": job.printer, "device_id": device_id})
        return job

    @staticmethod
    def _require_print_capability(actor, job, capability):
        _require_capability(actor, job.tenant_id, capability)
        if job.document.label_id and capability != "pos.document.cancel":
            from apps.prescription.label_printing import NON_PRINTABLE_EPISODE_STATES
            if job.document.label.episode.status in NON_PRINTABLE_EPISODE_STATES:
                raise ValidationError("This dispensing label is no longer valid for printing.")

    @classmethod
    @transaction.atomic
    def mark_rendered(cls, *, job, actor):
        cls._require_print_capability(actor, job, "pos.document.print")
        job = PosPrintJob.all_objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if job.status in {PosPrintJob.Status.RENDERED, PosPrintJob.Status.PRINTED}:
            return job
        if job.status != PosPrintJob.Status.QUEUED:
            raise ValidationError(f"Print job is {job.status}; it cannot be rendered.")
        job.status = PosPrintJob.Status.RENDERED
        job.save(update_fields=["status", "updated_at"])
        return job

    @classmethod
    @transaction.atomic
    def start_attempt(cls, *, job, actor):
        cls._require_print_capability(actor, job, "pos.document.print")
        job = PosPrintJob.all_objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if job.status == PosPrintJob.Status.PRINTED:
            return job
        if job.status not in {
            PosPrintJob.Status.QUEUED,
            PosPrintJob.Status.RENDERED,
        }:
            raise ValidationError(f"Print job is {job.status}; it cannot be sent.")
        job.status = PosPrintJob.Status.SENDING
        job.attempt_count += 1
        job.last_attempt_at = timezone.now()
        job.failure_code = ""
        job.failure_message = ""
        job.save(update_fields=["status", "attempt_count", "last_attempt_at", "failure_code", "failure_message", "updated_at"])
        return job

    @classmethod
    @transaction.atomic
    def record_result(cls, *, job, actor, succeeded, failure_code="", failure_message="", retryable=True):
        cls._require_print_capability(actor, job, "pos.document.print")
        job = PosPrintJob.all_objects.select_for_update().select_related("document").get(
            pk=job.pk, tenant_id=job.tenant_id
        )
        if job.status == PosPrintJob.Status.PRINTED:
            return job
        if job.status != PosPrintJob.Status.SENDING:
            raise ValidationError("A print result may be recorded only for a sending job.")
        if succeeded:
            if job.document.label_id and job.transport != PosPrintJob.Transport.SIMULATOR:
                from apps.prescription.label_printing import LabelPrintService
                LabelPrintService.record_print(label=job.document.label, actor=actor,
                    printer=job.printer, reason=job.reprint_reason, succeeded=True)
            job.status = PosPrintJob.Status.PRINTED
            job.printed_at = timezone.now()
            job.printed_by = actor
            job.failure_code = ""
            job.failure_message = ""
            event_type = "POS_PRINT_JOB_PRINTED"
        else:
            job.status = PosPrintJob.Status.RETRY_REQUIRED if retryable else PosPrintJob.Status.FAILED
            job.failure_code = str(failure_code or "TRANSPORT_FAILURE")[:64]
            job.failure_message = str(failure_message or "Printer transport did not confirm the document.")
            event_type = "POS_PRINT_JOB_FAILED"
        job.save()
        emit_event(
            tenant_id=str(job.tenant_id),
            aggregate_type="PosPrintJob",
            aggregate_id=str(job.id),
            event_type=event_type,
            payload={
                "document_id": str(job.document_id),
                "document_number": job.document.document_number,
                "status": job.status,
                "attempt_count": job.attempt_count,
                "failure_code": job.failure_code,
            },
        )
        return job

    @classmethod
    @transaction.atomic
    def retry(cls, *, job, actor):
        cls._require_print_capability(actor, job, "pos.document.print")
        job = PosPrintJob.all_objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if job.status != PosPrintJob.Status.RETRY_REQUIRED:
            raise ValidationError("Only a retry-required print job can be retried.")
        job.status = PosPrintJob.Status.QUEUED
        job.save(update_fields=["status", "updated_at"])
        return job

    @classmethod
    @transaction.atomic
    def cancel(cls, *, job, actor, reason):
        cls._require_print_capability(actor, job, "pos.document.cancel")
        if not reason or not reason.strip():
            raise ValidationError("Cancelling a print job requires a stated reason.")
        job = PosPrintJob.all_objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if job.status == PosPrintJob.Status.CANCELLED:
            return job
        if job.status not in {PosPrintJob.Status.QUEUED, PosPrintJob.Status.RENDERED}:
            raise ValidationError(f"Print job is {job.status}; it cannot be cancelled.")
        job.status = PosPrintJob.Status.CANCELLED
        job.cancelled_at = timezone.now()
        job.cancelled_by = actor
        job.cancellation_reason = reason.strip()
        job.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancelled_by",
                "cancellation_reason",
                "updated_at",
            ]
        )
        return job

    @classmethod
    @transaction.atomic
    def request_reprint(cls, *, document, actor, reason, printer="", transport=PosPrintJob.Transport.SIMULATOR):
        _require_capability(actor, document.tenant_id, "pos.document.reprint")
        if not reason or not reason.strip():
            raise ValidationError("A reprint requires a stated reason.")
        document = PosPrintDocument.all_objects.select_for_update().get(
            pk=document.pk, tenant_id=document.tenant_id
        )
        original = PosPrintJob.all_objects.filter(
            tenant=document.tenant,
            document=document,
            copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
        ).first()
        if not original or original.status != PosPrintJob.Status.PRINTED:
            raise ValidationError("A document can be reprinted only after its original print is confirmed.")
        copy_number = (
            PosPrintJob.all_objects.filter(tenant=document.tenant, document=document)
            .order_by("-copy_number")
            .values_list("copy_number", flat=True)
            .first()
            or 0
        ) + 1
        job = PosPrintJob.all_objects.create(
            tenant=document.tenant,
            document=document,
            branch=original.branch or getattr(document.episode, "branch", None),
            device_id=original.device_id,
            printer=printer or original.printer,
            transport=transport,
            copy_classification=PosPrintJob.CopyClassification.REPRINT,
            copy_number=copy_number,
            reprint_reason=reason.strip(),
            requested_by=actor,
            idempotency_key=f"reprint:{document.id}:{copy_number}",
        )
        return job
