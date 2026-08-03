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


class PractitionerRegistrationService:
    """Registers practitioners and records their licences.

    `PrescriberGovernanceService` could verify a practitioner and assess their
    authority, but nothing could create one -- so registration numbers,
    licensing bodies and controlled-medicine authority were written by whatever
    happened to insert the row.

    Two rules this service exists to hold:

    * A newly registered practitioner is UNVERIFIED. Registration records a
      claim about someone's credentials; verification is a separate, evidenced
      act, and creating a practitioner must never be a route to being treated
      as verified.
    * Controlled-medicine authority is never granted at registration. It is
      granted explicitly, by a named actor, against a licence -- because it is
      the flag that decides whether someone may prescribe a controlled drug.
    """

    @staticmethod
    @transaction.atomic
    def register_practitioner(
        *,
        tenant,
        first_name: str,
        last_name: str,
        profession: str,
        registration_number: str = "",
        licensing_body: str = "",
        licence_issue_date=None,
        licence_expiry_date=None,
        prescribing_scope: list | None = None,
        organization=None,
        phone: str = "",
        email: str = "",
        actor=None,
        verification_note: str = "MANUAL_INTERNAL_VERIFICATION",
    ) -> Practitioner:
        """Register a practitioner as UNVERIFIED.

        Idempotent on (tenant, registration_number) where a number is given,
        matching the partial unique constraint. Practitioners without a
        registration number are not deduplicated -- two people can share a name.
        """
        first_name = str(first_name or "").strip()
        last_name = str(last_name or "").strip()
        registration_number = str(registration_number or "").strip()

        if not first_name or not last_name:
            raise ValidationError("A practitioner requires a first and last name.")
        if profession not in dict(Practitioner.PROFESSION_CHOICES):
            known = ", ".join(dict(Practitioner.PROFESSION_CHOICES))
            raise ValidationError(f"Unknown profession {profession!r}. Known: {known}")
        if licence_issue_date and licence_expiry_date and licence_expiry_date < licence_issue_date:
            raise ValidationError("A licence cannot expire before it was issued.")
        if organization is not None and organization.tenant_id != tenant.id:
            raise ValidationError("A practitioner's organisation must belong to their tenant.")

        if registration_number:
            existing = Practitioner.all_objects.filter(
                tenant=tenant, registration_number=registration_number
            ).first()
            if existing is not None:
                return existing

        return Practitioner.all_objects.create(
            tenant=tenant,
            first_name=first_name,
            last_name=last_name,
            profession=profession,
            registration_number=registration_number,
            licensing_body=str(licensing_body or "").strip(),
            licence_issue_date=licence_issue_date,
            licence_expiry_date=licence_expiry_date,
            prescribing_scope=prescribing_scope or [],
            organization=organization,
            phone=str(phone or "").strip(),
            email=str(email or "").strip(),
            # Registration is a claim, not a verification.
            verification_state="UNVERIFIED",
            licence_status="UNVERIFIED",
            controlled_medicine_authority=False,
            status="ACTIVE",
            metadata={"verification_basis": verification_note},
        )

    @staticmethod
    @transaction.atomic
    def grant_controlled_medicine_authority(
        *, practitioner: Practitioner, actor, reason: str, evidence_reference: str = ""
    ) -> Practitioner:
        """Grant controlled-medicine authority, explicitly and attributably.

        Refused for an unverified practitioner: authority to prescribe a
        controlled drug cannot rest on an unchecked claim. Refused for an
        expired licence for the same reason.
        """
        if actor is None:
            raise PermissionDenied("Granting controlled-medicine authority requires a named actor.")
        _require_capability(actor, practitioner.tenant_id)
        if not str(reason or "").strip():
            raise ValidationError("Granting controlled-medicine authority requires a reason.")
        if practitioner.verification_state != "VERIFIED":
            raise ValidationError(
                "Controlled-medicine authority requires a verified practitioner. "
                f"This one is {practitioner.verification_state}."
            )
        expiry = practitioner.licence_expiry_date
        if expiry and expiry < timezone.now().date():
            raise ValidationError(
                f"The practitioner's licence expired on {expiry}. Renew it before "
                "granting controlled-medicine authority."
            )

        metadata = dict(practitioner.metadata or {})
        metadata["controlled_authority"] = {
            "granted_by": getattr(actor, "username", ""),
            "reason": reason,
            "evidence_reference": evidence_reference,
        }
        practitioner.controlled_medicine_authority = True
        practitioner.metadata = metadata
        practitioner.save(
            update_fields=["controlled_medicine_authority", "metadata", "updated_at"]
        )
        log_audit(
            tenant_id=practitioner.tenant_id,
            action="PRACTITIONER_CONTROLLED_AUTHORITY_GRANTED",
            model_name="Practitioner",
            object_id=practitioner.pk,
            actor_id=actor.id,
            metadata={"reason": reason, "evidence_reference": evidence_reference},
        )
        return practitioner

    @staticmethod
    @transaction.atomic
    def revoke_controlled_medicine_authority(
        *, practitioner: Practitioner, actor, reason: str
    ) -> Practitioner:
        """Withdraw controlled-medicine authority."""
        if actor is None:
            raise PermissionDenied("Revoking controlled-medicine authority requires a named actor.")
        _require_capability(actor, practitioner.tenant_id)
        if not str(reason or "").strip():
            raise ValidationError("Revoking controlled-medicine authority requires a reason.")

        metadata = dict(practitioner.metadata or {})
        metadata["controlled_authority_revoked"] = {
            "revoked_by": getattr(actor, "username", ""), "reason": reason,
        }
        practitioner.controlled_medicine_authority = False
        practitioner.metadata = metadata
        practitioner.save(
            update_fields=["controlled_medicine_authority", "metadata", "updated_at"]
        )
        log_audit(
            tenant_id=practitioner.tenant_id,
            action="PRACTITIONER_CONTROLLED_AUTHORITY_REVOKED",
            model_name="Practitioner",
            object_id=practitioner.pk,
            actor_id=actor.id,
            metadata={"reason": reason},
        )
        return practitioner
