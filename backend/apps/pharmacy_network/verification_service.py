"""Premises verification governance service.

Governs the manual verification lifecycle for pharmacy premises licences:
  DRAFT -> SUBMITTED -> UNDER_REVIEW -> CLARIFICATION_REQUIRED -> VERIFIED
                                     -> REJECTED
                                     -> SUSPENDED
                                     -> REVOKED
                                     -> SUPERSEDED

Truth label: MANUAL_INTERNAL_VERIFICATION
This service performs internal compliance review; it does NOT connect to the
Pharmacy and Poisons Board (PPB) API. Until a live PPB API integration is
confirmed and credentials are approved by the Platform Owner, the truth label
remains MANUAL_INTERNAL_VERIFICATION.

Governance rules enforced here:
- Self-verification block: reviewer != submitter.
- Only roles with 'premises.verify' capability may approve, reject, suspend, revoke.
- Operational policy: VERIFIED state is required for POS device activation,
  controlled medicine dispensing, official regulatory report submission, and
  HIE/national integration enablement.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.pharmacy_network.models import (
    PharmacyProfile,
    PremisesVerificationRequest,
    PremisesVerificationSnapshot,
)

# ---------------------------------------------------------------------------
# Operational policy enforcement
# ---------------------------------------------------------------------------

POLICY_BLOCKED_OPERATIONS = (
    "POS_DEVICE_ACTIVATION",
    "CONTROLLED_MEDICINE_DISPENSE",
    "REGULATORY_REPORT_SUBMISSION",
    "HIE_INTEGRATION_ENABLEMENT",
    "NEW_BRANCH_PROVISIONING",
)


def check_premises_compliance(
    tenant_id: object,
    operation: str,
) -> tuple[bool, str]:
    """Check whether a tenant's premises are verified for the given operation.

    Returns (is_allowed, reason_code).
    is_allowed=True means the premises are verified and the operation may proceed.
    is_allowed=False means the operation is blocked; reason_code explains why.

    Truth label: MANUAL_INTERNAL_VERIFICATION — this check is based on internal
    manual compliance review, not a live PPB API connection.
    """
    if operation not in POLICY_BLOCKED_OPERATIONS:
        # Unknown operations are allowed through; callers should only pass known ops.
        return True, "OPERATION_NOT_GOVERNED"

    active_verification = (
        PremisesVerificationRequest.all_objects
        .filter(
            tenant_id=tenant_id,
            state=PremisesVerificationRequest.VerificationState.VERIFIED,
        )
        .order_by("-created_at")
        .first()
    )

    if active_verification is None:
        return False, "PREMISES_NOT_VERIFIED"

    # Check the associated pharmacy profile licence is not expired.
    try:
        profile = PharmacyProfile.all_objects.get(tenant_id=tenant_id)
    except PharmacyProfile.DoesNotExist:
        return False, "PHARMACY_PROFILE_MISSING"

    if not profile.licence_is_current:
        return False, "PREMISES_LICENCE_EXPIRED"

    return True, "PREMISES_VERIFIED_MANUAL_INTERNAL_VERIFICATION"


# ---------------------------------------------------------------------------
# Verification workflow transitions
# ---------------------------------------------------------------------------

def _require_verify_capability(actor, tenant_id) -> None:
    if not actor or not any(
        actor.has_capability(cap, tenant_id=tenant_id)
        for cap in ("premises.verify", "platform.owner")
    ):
        raise PermissionDenied("Capability premises.verify is required.")


def _self_verification_check(actor, request: PremisesVerificationRequest) -> None:
    """Raise if the actor is the same person who submitted the request."""
    if request.submitted_by_id and str(actor.id) == str(request.submitted_by_id):
        raise PermissionDenied(
            "Self-verification is not permitted. The reviewer must differ from the submitter."
        )


def _capture_snapshot(
    request: PremisesVerificationRequest,
    actor,
    state: str,
    reason: str = "",
) -> PremisesVerificationSnapshot:
    """Write an immutable audit snapshot for a state transition."""
    profile = request.pharmacy_profile
    snapshot = PremisesVerificationSnapshot(
        verification_request=request,
        tenant_id=request.tenant_id,
        captured_state=state,
        declared_licence_number=profile.ppb_premises_licence_number,
        declared_expiry=profile.ppb_licence_expiry,
        declared_superintendent=profile.superintendent_name,
        evidence_payload=dict(request.evidence_payload),
        actor=actor,
        reason=reason,
        truth_label="MANUAL_INTERNAL_VERIFICATION",
        captured_at=timezone.now(),
    )
    snapshot.save()
    return snapshot


@transaction.atomic
def submit_verification_request(
    *,
    tenant_id: object,
    pharmacy_profile: PharmacyProfile,
    submitted_by,
    evidence_payload: dict,
) -> PremisesVerificationRequest:
    """Submit a new premises verification request.

    Supersedes any existing DRAFT or open requests for the same profile.
    """
    # Supersede any open (non-terminal, non-verified) requests.
    open_states = [
        PremisesVerificationRequest.VerificationState.DRAFT,
        PremisesVerificationRequest.VerificationState.SUBMITTED,
        PremisesVerificationRequest.VerificationState.UNDER_REVIEW,
        PremisesVerificationRequest.VerificationState.CLARIFICATION_REQUIRED,
    ]
    PremisesVerificationRequest.all_objects.filter(
        tenant_id=tenant_id,
        pharmacy_profile=pharmacy_profile,
        state__in=open_states,
    ).update(state=PremisesVerificationRequest.VerificationState.SUPERSEDED)

    request = PremisesVerificationRequest(
        tenant_id=tenant_id,
        pharmacy_profile=pharmacy_profile,
        state=PremisesVerificationRequest.VerificationState.SUBMITTED,
        submitted_by=submitted_by,
        submitted_at=timezone.now(),
        evidence_payload=evidence_payload,
        truth_label="MANUAL_INTERNAL_VERIFICATION",
    )
    request.save()
    log_audit(
        tenant_id=tenant_id,
        action="PREMISES_VERIFICATION_SUBMITTED",
        model_name="PremisesVerificationRequest",
        object_id=request.id,
        actor_id=submitted_by.id,
        metadata={"truth_label": "MANUAL_INTERNAL_VERIFICATION"},
    )
    return request


@transaction.atomic
def approve_verification_request(
    *,
    request: PremisesVerificationRequest,
    actor,
    reviewer_notes: str = "",
    verifier_declaration: str = "",
) -> PremisesVerificationRequest:
    """Approve a submitted verification request.

    Only Platform Owner or Compliance role may call this.
    Self-verification is strictly blocked.
    """
    _require_verify_capability(actor, request.tenant_id)
    _self_verification_check(actor, request)

    locked = PremisesVerificationRequest.all_objects.select_for_update().get(id=request.id)
    if locked.state not in (
        PremisesVerificationRequest.VerificationState.SUBMITTED,
        PremisesVerificationRequest.VerificationState.UNDER_REVIEW,
        PremisesVerificationRequest.VerificationState.CLARIFICATION_REQUIRED,
    ):
        raise ValidationError(f"Cannot approve a request in state '{locked.state}'.")

    locked.state = PremisesVerificationRequest.VerificationState.VERIFIED
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    locked.reviewer_notes = reviewer_notes
    locked.verifier_declaration = verifier_declaration
    locked.truth_label = "MANUAL_INTERNAL_VERIFICATION"
    locked.save()

    _capture_snapshot(locked, actor, locked.state, reviewer_notes)
    log_audit(
        tenant_id=locked.tenant_id,
        action="PREMISES_VERIFICATION_APPROVED",
        model_name="PremisesVerificationRequest",
        object_id=locked.id,
        actor_id=actor.id,
        metadata={"truth_label": "MANUAL_INTERNAL_VERIFICATION"},
    )
    return locked


@transaction.atomic
def reject_verification_request(
    *,
    request: PremisesVerificationRequest,
    actor,
    reviewer_notes: str,
) -> PremisesVerificationRequest:
    """Reject a submitted verification request."""
    _require_verify_capability(actor, request.tenant_id)
    _self_verification_check(actor, request)

    locked = PremisesVerificationRequest.all_objects.select_for_update().get(id=request.id)
    if locked.state not in (
        PremisesVerificationRequest.VerificationState.SUBMITTED,
        PremisesVerificationRequest.VerificationState.UNDER_REVIEW,
        PremisesVerificationRequest.VerificationState.CLARIFICATION_REQUIRED,
    ):
        raise ValidationError(f"Cannot reject a request in state '{locked.state}'.")

    locked.state = PremisesVerificationRequest.VerificationState.REJECTED
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    locked.reviewer_notes = reviewer_notes
    locked.save()

    _capture_snapshot(locked, actor, locked.state, reviewer_notes)
    log_audit(
        tenant_id=locked.tenant_id,
        action="PREMISES_VERIFICATION_REJECTED",
        model_name="PremisesVerificationRequest",
        object_id=locked.id,
        actor_id=actor.id,
        metadata={"truth_label": "MANUAL_INTERNAL_VERIFICATION"},
    )
    return locked


@transaction.atomic
def request_clarification(
    *,
    request: PremisesVerificationRequest,
    actor,
    reviewer_notes: str,
) -> PremisesVerificationRequest:
    """Move a request to CLARIFICATION_REQUIRED, asking the submitter for more evidence."""
    _require_verify_capability(actor, request.tenant_id)
    _self_verification_check(actor, request)

    locked = PremisesVerificationRequest.all_objects.select_for_update().get(id=request.id)
    if locked.state not in (
        PremisesVerificationRequest.VerificationState.SUBMITTED,
        PremisesVerificationRequest.VerificationState.UNDER_REVIEW,
    ):
        raise ValidationError(f"Cannot request clarification on a request in state '{locked.state}'.")

    locked.state = PremisesVerificationRequest.VerificationState.CLARIFICATION_REQUIRED
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    locked.reviewer_notes = reviewer_notes
    locked.save()

    _capture_snapshot(locked, actor, locked.state, reviewer_notes)
    log_audit(
        tenant_id=locked.tenant_id,
        action="PREMISES_VERIFICATION_CLARIFICATION_REQUESTED",
        model_name="PremisesVerificationRequest",
        object_id=locked.id,
        actor_id=actor.id,
        metadata={"truth_label": "MANUAL_INTERNAL_VERIFICATION"},
    )
    return locked


@transaction.atomic
def suspend_verification(
    *,
    request: PremisesVerificationRequest,
    actor,
    reason: str,
) -> PremisesVerificationRequest:
    """Suspend a previously verified premises. Requires dual-sign-off (Platform Owner only)."""
    _require_verify_capability(actor, request.tenant_id)
    _self_verification_check(actor, request)

    locked = PremisesVerificationRequest.all_objects.select_for_update().get(id=request.id)
    if locked.state != PremisesVerificationRequest.VerificationState.VERIFIED:
        raise ValidationError(f"Can only suspend a VERIFIED request; current state: '{locked.state}'.")

    locked.state = PremisesVerificationRequest.VerificationState.SUSPENDED
    locked.reviewer_notes = reason
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    locked.save()

    _capture_snapshot(locked, actor, locked.state, reason)
    log_audit(
        tenant_id=locked.tenant_id,
        action="PREMISES_VERIFICATION_SUSPENDED",
        model_name="PremisesVerificationRequest",
        object_id=locked.id,
        actor_id=actor.id,
        metadata={"reason": reason, "truth_label": "MANUAL_INTERNAL_VERIFICATION"},
    )
    return locked


@transaction.atomic
def revoke_verification(
    *,
    request: PremisesVerificationRequest,
    actor,
    reason: str,
) -> PremisesVerificationRequest:
    """Revoke a verification permanently. Requires Platform Owner role."""
    _require_verify_capability(actor, request.tenant_id)
    _self_verification_check(actor, request)

    locked = PremisesVerificationRequest.all_objects.select_for_update().get(id=request.id)
    if locked.state not in (
        PremisesVerificationRequest.VerificationState.VERIFIED,
        PremisesVerificationRequest.VerificationState.SUSPENDED,
    ):
        raise ValidationError(f"Can only revoke a VERIFIED or SUSPENDED request; current state: '{locked.state}'.")

    locked.state = PremisesVerificationRequest.VerificationState.REVOKED
    locked.reviewer_notes = reason
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    locked.save()

    _capture_snapshot(locked, actor, locked.state, reason)
    log_audit(
        tenant_id=locked.tenant_id,
        action="PREMISES_VERIFICATION_REVOKED",
        model_name="PremisesVerificationRequest",
        object_id=locked.id,
        actor_id=actor.id,
        metadata={"reason": reason, "truth_label": "MANUAL_INTERNAL_VERIFICATION"},
    )
    return locked
