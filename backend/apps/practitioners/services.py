from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.practitioners.models import Practitioner, PractitionerLicence
from apps.workflows.service import emit_event


def _require_capability(actor, tenant_id):
    if not actor or not any(
        actor.has_capability(capability, tenant_id=tenant_id)
        for capability in ("prescribers.verify", "practitioners.write")
    ):
        raise PermissionDenied("Capability prescribers.verify is required.")


class PrescriberGovernanceService:
    @staticmethod
    def authority_findings(
        *,
        practitioner,
        prescription_date=None,
        controlled=False,
        required_scope="",
    ):
        findings = []
        effective_date = prescription_date or timezone.localdate()
        if practitioner.status != "ACTIVE":
            findings.append(("PRESCRIBER_INACTIVE", "CRITICAL", "Prescriber is inactive."))
        if practitioner.verification_state != "VERIFIED":
            findings.append(
                ("PRESCRIBER_UNVERIFIED", "CRITICAL", "Prescriber is not verified.")
            )
        if not practitioner.registration_number:
            findings.append(
                (
                    "PRESCRIBER_REGISTRATION_MISSING",
                    "CRITICAL",
                    "Prescriber registration number is missing.",
                )
            )
        if practitioner.licence_status not in {"VALID", "ACTIVE"}:
            findings.append(
                ("PRESCRIBER_LICENCE_INVALID", "CRITICAL", "Prescriber licence is invalid.")
            )
        if (
            practitioner.licence_issue_date
            and practitioner.licence_issue_date > effective_date
        ):
            findings.append(
                (
                    "PRESCRIBER_LICENCE_NOT_YET_VALID",
                    "CRITICAL",
                    "Prescriber licence was not valid on the prescription date.",
                )
            )
        if (
            practitioner.licence_expiry_date
            and practitioner.licence_expiry_date < effective_date
        ):
            findings.append(
                ("PRESCRIBER_LICENCE_EXPIRED", "CRITICAL", "Prescriber licence expired.")
            )
        if required_scope and required_scope not in (practitioner.prescribing_scope or []):
            findings.append(
                (
                    "PRESCRIBER_SCOPE_INVALID",
                    "CRITICAL",
                    "Prescription is outside the prescriber's verified scope.",
                )
            )
        if controlled and not practitioner.controlled_medicine_authority:
            findings.append(
                (
                    "CONTROLLED_AUTHORITY_MISSING",
                    "CRITICAL",
                    "Prescriber lacks controlled-medicine authority.",
                )
            )
        return findings

    @classmethod
    @transaction.atomic
    def verify(
        cls,
        *,
        practitioner,
        actor,
        verification_state="VERIFIED",
        licence_status=None,
        controlled_medicine_authority=None,
    ):
        _require_capability(actor, practitioner.tenant_id)
        locked = Practitioner.all_objects.select_for_update().get(
            id=practitioner.id,
            tenant_id=practitioner.tenant_id,
        )
        if licence_status is not None:
            locked.licence_status = licence_status
        if controlled_medicine_authority is not None:
            locked.controlled_medicine_authority = controlled_medicine_authority
        if verification_state == "VERIFIED":
            findings = cls.authority_findings(
                practitioner=locked,
                controlled=False,
            )
            findings = [
                finding
                for finding in findings
                if finding[0] not in {"PRESCRIBER_UNVERIFIED"}
            ]
            if findings:
                raise ValidationError(
                    {code: message for code, _severity, message in findings}
                )
        locked.verification_state = verification_state
        locked.verified_by = actor
        locked.verified_at = timezone.now()
        locked.save()
        PractitionerLicence.all_objects.filter(
            tenant_id=locked.tenant_id,
            practitioner=locked,
            status__in=["VALID", "ACTIVE"],
        ).update(
            verification_state=verification_state,
            verified_by=actor,
            verified_at=locked.verified_at,
        )
        log_audit(
            tenant_id=locked.tenant_id,
            action="PRESCRIBER_VERIFIED",
            model_name="Practitioner",
            object_id=locked.id,
            actor_id=actor.id,
            metadata={"verification_state": verification_state},
        )
        emit_event(
            tenant_id=locked.tenant_id,
            aggregate_type="Practitioner",
            aggregate_id=locked.id,
            event_type="PrescriberVerified",
            payload={
                "tenant": str(locked.tenant_id),
                "actor": str(actor.id),
                "prescriber": str(locked.id),
                "verification_state": verification_state,
                "event_version": 1,
                "timestamp": timezone.now().isoformat(),
            },
        )
        return locked
