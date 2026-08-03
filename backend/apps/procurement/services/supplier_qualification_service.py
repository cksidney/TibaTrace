"""Supplier qualification lifecycle.

`SupplierGovernanceService` could *verify* a qualification and read the valid
set, but nothing could create one -- so every qualification in the repository
was written straight to the ORM by a seed command. That skipped the rules that
matter most here, because a qualification is what permits a supplier to supply
controlled drugs and cold-chain lines. A row invented without checks is a
permission granted without checks.

The state machine:

    (register) -> PENDING -> VERIFIED -> EXPIRED
                     |          |
                     |          +-----> REVOKED
                     +-------------> REJECTED

PENDING is the only entry point. Nothing may be created VERIFIED, and the
verifier may not be the submitter -- that pairing is the whole point of
recording a submitter.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.procurement.models import Supplier, SupplierQualification
from apps.workflows.service import emit_event

Status = SupplierQualification.QualificationVerificationStatus
QualificationType = SupplierQualification.QualificationType

#: Verification is internal document review. Nothing contacts the PPB, KRA or
#: any registry, so nothing may record that it did.
MANUAL_VERIFICATION = "MANUAL_INTERNAL_VERIFICATION"

#: A supplier in one of these states may not gain new qualifications. Suspended
#: and disqualified suppliers are barred for cause; archived ones are closed.
BLOCKED_SUPPLIER_STATUSES = frozenset(
    {Supplier.Status.SUSPENDED, Supplier.Status.DISQUALIFIED, Supplier.Status.ARCHIVED}
)

#: States in which a qualification still occupies its type/number slot. Used to
#: block a duplicate, while leaving rejected and revoked history queryable.
OCCUPYING_STATUSES = frozenset({Status.PENDING, Status.VERIFIED})

#: Terminal states. Immutable evidence: once a qualification has been verified,
#: rejected, revoked or expired, that decision is not edited in place.
TERMINAL_STATUSES = frozenset({Status.REJECTED, Status.REVOKED, Status.EXPIRED})

#: The qualification a supplier must hold to supply each restricted category.
CONTROLLED_DRUG_QUALIFICATION = QualificationType.CONTROLLED_DRUG_LICENCE
COLD_CHAIN_QUALIFICATION = QualificationType.COLD_CHAIN_AUTHORIZATION


def _audit(qualification: SupplierQualification, action: str, actor, **metadata) -> None:
    log_audit(
        tenant_id=qualification.tenant_id,
        action=action,
        model_name="SupplierQualification",
        object_id=qualification.pk,
        actor_id=getattr(actor, "id", None),
        metadata={
            "supplier": qualification.supplier.supplier_code,
            "qualification_type": qualification.qualification_type,
            **metadata,
        },
    )
    if qualification.tenant_id:
        emit_event(
            tenant_id=qualification.tenant_id,
            aggregate_type="SUPPLIER_QUALIFICATION",
            aggregate_id=str(qualification.pk),
            event_type=action,
            payload={"status": qualification.verification_status, **metadata},
        )


class SupplierQualificationService:
    """Registers and governs supplier qualifications."""

    @staticmethod
    @transaction.atomic
    def register_qualification(
        *,
        tenant,
        supplier: Supplier,
        qualification_type: str,
        licence_number: str,
        issuing_authority: str,
        effective_date: date,
        expiry_date: date,
        submitted_by=None,
        document_reference: str = "",
    ) -> SupplierQualification:
        """Put a qualification forward for verification.

        Always lands in PENDING. There is no argument that creates a verified
        qualification, because a caller that could pass `status=VERIFIED` would
        make verification optional.

        Idempotent on (tenant, supplier, type, licence number) while a
        qualification is still occupying that slot.
        """
        licence_number = str(licence_number or "").strip()
        issuing_authority = str(issuing_authority or "").strip()

        if supplier is None:
            raise ValidationError("A qualification requires a supplier.")
        if supplier.tenant_id != getattr(tenant, "id", None):
            raise ValidationError("The supplier belongs to a different tenant.")
        if qualification_type not in QualificationType.values:
            known = ", ".join(QualificationType.values)
            raise ValidationError(
                f"Unknown qualification type {qualification_type!r}. Known: {known}"
            )
        if not licence_number:
            raise ValidationError("A qualification requires a licence or certificate number.")
        if not issuing_authority:
            raise ValidationError("A qualification requires an issuing authority.")
        if effective_date is None or expiry_date is None:
            raise ValidationError("A qualification requires both effective and expiry dates.")
        if expiry_date < effective_date:
            raise ValidationError("A qualification cannot expire before it takes effect.")
        if expiry_date < timezone.localdate():
            # An already-expired document must not enter the pipeline: it would
            # sit in PENDING looking like work in progress, and verifying it
            # would produce a VERIFIED row that is expired on arrival.
            raise ValidationError(
                f"The {qualification_type} expired on {expiry_date}. An expired document "
                "cannot be registered; register the renewal instead."
            )
        if supplier.status in BLOCKED_SUPPLIER_STATUSES:
            raise ValidationError(
                f"Supplier {supplier.supplier_code} is {supplier.status} and cannot receive "
                "new qualifications."
            )

        existing = SupplierQualification.all_objects.filter(
            tenant=tenant,
            supplier=supplier,
            qualification_type=qualification_type,
            licence_number=licence_number,
            verification_status__in=OCCUPYING_STATUSES,
        ).first()
        if existing is not None:
            return existing

        # A different licence number for a type the supplier already holds is a
        # replacement, not a duplicate -- but two live ones would make "which
        # licence authorised this?" unanswerable, so the caller must supersede
        # the incumbent first.
        conflicting = SupplierQualification.all_objects.filter(
            tenant=tenant,
            supplier=supplier,
            qualification_type=qualification_type,
            verification_status__in=OCCUPYING_STATUSES,
        ).exclude(licence_number=licence_number).first()
        if conflicting is not None:
            raise ValidationError(
                f"Supplier {supplier.supplier_code} already holds a "
                f"{qualification_type} ({conflicting.licence_number}, "
                f"{conflicting.verification_status}). Revoke or expire it before "
                "registering a different licence number."
            )

        qualification = SupplierQualification.all_objects.create(
            tenant=tenant,
            supplier=supplier,
            qualification_type=qualification_type,
            licence_number=licence_number,
            issuing_authority=issuing_authority,
            effective_date=effective_date,
            expiry_date=expiry_date,
            document_reference=document_reference,
            verification_status=Status.PENDING,
            submitted_by=submitted_by,
            submitted_at=timezone.now(),
        )
        _audit(qualification, "SUPPLIER_QUALIFICATION_REGISTERED", submitted_by,
               licence_number=licence_number)
        return qualification

    @staticmethod
    @transaction.atomic
    def verify_qualification(
        *, qualification: SupplierQualification, verifier, evidence_reference: str = "",
    ) -> SupplierQualification:
        """Accept a qualification after internal document review.

        Refuses self-verification. Without a distinct reviewer, one person can
        register a controlled-drug licence and approve their own evidence,
        which is the exact control this exists to provide.
        """
        if verifier is None:
            raise PermissionDenied("Verifying a qualification requires a named verifier.")
        if qualification.verification_status != Status.PENDING:
            raise ValidationError(
                f"Only a PENDING qualification can be verified; this one is "
                f"{qualification.verification_status}."
            )
        if (
            qualification.submitted_by_id
            and str(qualification.submitted_by_id) == str(verifier.id)
        ):
            raise PermissionDenied(
                "Self-verification is not permitted. The verifier must differ from the "
                "person who registered the qualification."
            )
        if qualification.expiry_date < timezone.localdate():
            raise ValidationError(
                f"The qualification expired on {qualification.expiry_date} and cannot be "
                "verified. Register the renewal instead."
            )

        qualification.verification_status = Status.VERIFIED
        qualification.verified_by = verifier
        qualification.verified_at = timezone.now()
        qualification.verification_basis = MANUAL_VERIFICATION
        if evidence_reference:
            qualification.document_reference = evidence_reference
        qualification.save(
            update_fields=[
                "verification_status", "verified_by", "verified_at",
                "verification_basis", "document_reference", "updated_at",
            ]
        )
        _audit(qualification, "SUPPLIER_QUALIFICATION_VERIFIED", verifier,
               verification_basis=MANUAL_VERIFICATION)
        return qualification

    @staticmethod
    @transaction.atomic
    def reject_qualification(
        *, qualification: SupplierQualification, reviewer, reason: str
    ) -> SupplierQualification:
        """Refuse a qualification. Terminal; the row stays queryable."""
        if reviewer is None:
            raise PermissionDenied("Rejecting a qualification requires a named reviewer.")
        if not str(reason or "").strip():
            raise ValidationError("Rejecting a qualification requires a reason.")
        if qualification.verification_status != Status.PENDING:
            raise ValidationError(
                f"Only a PENDING qualification can be rejected; this one is "
                f"{qualification.verification_status}."
            )
        if (
            qualification.submitted_by_id
            and str(qualification.submitted_by_id) == str(reviewer.id)
        ):
            raise PermissionDenied(
                "The reviewer must differ from the person who registered the qualification."
            )

        qualification.verification_status = Status.REJECTED
        qualification.decision_reason = reason
        qualification.verified_by = reviewer
        qualification.verified_at = timezone.now()
        qualification.save(
            update_fields=[
                "verification_status", "decision_reason", "verified_by",
                "verified_at", "updated_at",
            ]
        )
        _audit(qualification, "SUPPLIER_QUALIFICATION_REJECTED", reviewer, reason=reason)
        return qualification

    @staticmethod
    @transaction.atomic
    def revoke_qualification(
        *, qualification: SupplierQualification, actor, reason: str
    ) -> SupplierQualification:
        """Withdraw a verified qualification for cause.

        Distinct from expiry: expiry is the passage of time, revocation is a
        decision. Conflating them would lose why the supplier lost the
        authority.
        """
        if actor is None:
            raise PermissionDenied("Revoking a qualification requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Revoking a qualification requires a reason.")
        if qualification.verification_status != Status.VERIFIED:
            raise ValidationError(
                f"Only a VERIFIED qualification can be revoked; this one is "
                f"{qualification.verification_status}."
            )

        qualification.verification_status = Status.REVOKED
        qualification.decision_reason = reason
        qualification.save(
            update_fields=["verification_status", "decision_reason", "updated_at"]
        )
        _audit(qualification, "SUPPLIER_QUALIFICATION_REVOKED", actor, reason=reason)
        return qualification

    @staticmethod
    @transaction.atomic
    def expire_qualification(
        *, qualification: SupplierQualification, as_of: date | None = None
    ) -> SupplierQualification:
        """Mark a qualification expired once its expiry date has passed.

        Refuses to expire one that is still current: expiring early would
        remove a supplier's authority on a date nobody decided.
        """
        as_of = as_of or timezone.localdate()
        if qualification.verification_status not in {Status.VERIFIED, Status.PENDING}:
            raise ValidationError(
                f"A {qualification.verification_status} qualification cannot expire."
            )
        if qualification.expiry_date >= as_of:
            raise ValidationError(
                f"The qualification is current until {qualification.expiry_date}; "
                f"it cannot be expired as of {as_of}."
            )

        qualification.verification_status = Status.EXPIRED
        qualification.save(update_fields=["verification_status", "updated_at"])
        _audit(qualification, "SUPPLIER_QUALIFICATION_EXPIRED", None,
               expiry_date=str(qualification.expiry_date))
        return qualification

    # -- queries -----------------------------------------------------------

    @staticmethod
    def current_qualifications(*, supplier: Supplier, on_date: date | None = None):
        """Verified, unexpired qualifications, ordered deterministically."""
        on_date = on_date or timezone.localdate()
        return (
            SupplierQualification.all_objects.filter(
                supplier=supplier,
                verification_status=Status.VERIFIED,
                effective_date__lte=on_date,
                expiry_date__gte=on_date,
            )
            .order_by("qualification_type", "licence_number")
        )

    @staticmethod
    def holds(*, supplier: Supplier, qualification_type: str,
              on_date: date | None = None) -> bool:
        """Whether a supplier currently holds a given qualification."""
        return SupplierQualificationService.current_qualifications(
            supplier=supplier, on_date=on_date
        ).filter(qualification_type=qualification_type).exists()
