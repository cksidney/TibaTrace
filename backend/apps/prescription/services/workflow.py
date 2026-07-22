from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from apps.core.request_context import get_current_request_id
from apps.prescription.models import Prescription, PrescriptionItem, PrescriptionWorkflowEvent


class PrescriptionWorkflowError(ValueError):
    pass


class PrescriptionWorkflowService:
    TRANSITIONS = {
        "DRAFT": {"CLINICAL_REVIEW"},
        "CLINICAL_REVIEW": {"BLOCKED", "APPROVED"},
        "BLOCKED": {"CLINICAL_REVIEW"},
        "APPROVED": {"DISPENSING"},
        "DISPENSING": {"READY_FOR_PAYMENT"},
        "READY_FOR_PAYMENT": {"APPROVED", "PAID"},
        "PAID": {"DISPENSED"},
        "DISPENSED": {"REVERSED"},
        "REVERSED": set(),
    }
    CAPABILITIES = {
        "CLINICAL_REVIEW": "prescriptions.review",
        "APPROVED": "prescriptions.approve",
        "DISPENSING": "dispensing.prepare",
        "READY_FOR_PAYMENT": "dispensing.prepare",
        "PAID": "prescriptions.record_payment",
        "DISPENSED": "dispensing.complete",
        "REVERSED": "dispensing.reverse",
    }

    @staticmethod
    def context_hash(prescription: Prescription) -> str:
        lines = list(
            PrescriptionItem.all_objects.filter(
                tenant_id=prescription.tenant_id,
                prescription_id=prescription.id,
            ).order_by("id").values(
                "id",
                "canonical_medicine_id",
                "medication_name",
                "dosage_instruction",
                "dose_amount",
                "dose_unit",
                "frequency_per_day",
                "duration_days",
                "quantity",
                "is_controlled",
            )
        )
        payload = {
            "patient_id": str(prescription.patient_id),
            "practitioner_id": str(prescription.practitioner_id),
            "issued_at": prescription.issued_at.isoformat() if prescription.issued_at else None,
            "expires_at": prescription.expires_at.isoformat() if prescription.expires_at else None,
            "lines": lines,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    @classmethod
    @transaction.atomic
    def transition(
        cls,
        *,
        prescription_id,
        tenant_id,
        actor,
        target_state: str,
        reason: str = "",
        clinical_evaluation_id=None,
        payment_reference: str = "",
    ) -> Prescription:
        prescription = Prescription.all_objects.select_for_update().filter(
            id=prescription_id,
            tenant_id=tenant_id,
        ).first()
        if not prescription:
            raise PrescriptionWorkflowError("Prescription is unavailable in the active tenant.")

        target_state = str(target_state or "").upper()
        if target_state not in cls.TRANSITIONS.get(prescription.workflow_state, set()):
            raise PrescriptionWorkflowError(
                f"Transition from {prescription.workflow_state} to {target_state} is not allowed."
            )

        capability = cls.CAPABILITIES.get(target_state)
        if capability and not actor.has_capability(capability, tenant_id=tenant_id):
            raise PermissionError(f"Capability {capability} is required.")

        current_hash = cls.context_hash(prescription)
        if target_state in {"BLOCKED", "APPROVED"}:
            from apps.cds.models import ClinicalEvaluation

            evaluation = ClinicalEvaluation.all_objects.filter(
                id=clinical_evaluation_id,
                tenant_id=tenant_id,
                prescription_id=prescription.id,
            ).first()
            if not evaluation or evaluation.context_hash != current_hash:
                raise PrescriptionWorkflowError("A current tenant-owned clinical evaluation is required.")
            if evaluation.status in {"KNOWLEDGE_UNAVAILABLE", "ERROR"}:
                raise PrescriptionWorkflowError("Clinical knowledge is unavailable; prescription remains blocked.")
            if target_state == "APPROVED" and evaluation.status == "BLOCK":
                raise PrescriptionWorkflowError("Blocking clinical findings remain unresolved.")
            if target_state == "BLOCKED" and evaluation.status not in {"BLOCK", "KNOWLEDGE_UNAVAILABLE", "ERROR"}:
                raise PrescriptionWorkflowError("The clinical evaluation does not require a blocked state.")
            prescription.clinical_review_id = evaluation.id
            prescription.clinical_context_hash = current_hash
            if target_state == "APPROVED":
                prescription.approved_by = actor
                prescription.approved_at = timezone.now()

        if target_state in {"DISPENSING", "READY_FOR_PAYMENT", "PAID", "DISPENSED"}:
            if not prescription.clinical_review_id or prescription.clinical_context_hash != current_hash:
                raise PrescriptionWorkflowError("Clinical approval is missing or stale.")

        if target_state == "PAID":
            payment_reference = str(payment_reference or "").strip()
            if not payment_reference:
                raise PrescriptionWorkflowError("Authoritative payment evidence is required.")
            prescription.payment_reference = payment_reference

        if target_state == "REVERSED" and not str(reason or "").strip():
            raise PrescriptionWorkflowError("A reversal reason is required.")

        previous = prescription.workflow_state
        prescription.workflow_state = target_state
        if target_state == "DISPENSED":
            prescription.status = "DISPENSED"
        elif target_state == "REVERSED":
            prescription.status = "CANCELLED"
        prescription.save()
        PrescriptionWorkflowEvent.all_objects.create(
            tenant_id=tenant_id,
            prescription=prescription,
            from_state=previous,
            to_state=target_state,
            actor=actor,
            reason=str(reason or ""),
            context_hash=current_hash,
            correlation_id=get_current_request_id() or "",
        )
        return prescription
