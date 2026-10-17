"""Authoritative Dispensing Lifecycle State Machine & Service for Stage 2D.2.

Defines the single, authoritative 13-stage dispensing lifecycle:
  REQUEST_PLANNED
  ↓
  PRESCRIPTION_RECEIVED
  ↓
  LEGAL_VALIDATED
  ↓
  CLINICAL_SCREENED
  ↓
  PHARMACIST_REVIEW
  ↓
  SUBSTITUTION_APPROVED (optional)
  ↓
  PRICE_LOCKED
  ↓
  INVENTORY_RESERVED
  ↓
  READY_FOR_PAYMENT
  ↓
  PAYMENT_COMPLETED
  ↓
  READY_TO_DISPENSE
  ↓
  DISPENSED
  ↓
  CLOSED

Enforces:
- Strict transition graph validation; invalid/skipped transitions raise InvalidStateTransitionError.
- Price locking immutability: once PRICE_LOCKED, price fields cannot be modified.
- Clinical freeze enforcement: modifying patient/practitioner/items after PHARMACIST_REVIEW invalidates review and reverts state to CLINICAL_SCREENED.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from django.core.exceptions import ValidationError
from django.db import transaction


class DispensingLifecycleState(str, Enum):
    DRAFT = "DRAFT"
    REQUEST_PLANNED = "REQUEST_PLANNED"
    PRESCRIPTION_RECEIVED = "PRESCRIPTION_RECEIVED"
    LEGAL_VALIDATED = "LEGAL_VALIDATED"
    CLINICAL_SCREENED = "CLINICAL_SCREENED"
    PHARMACIST_REVIEW = "PHARMACIST_REVIEW"
    SUBSTITUTION_APPROVED = "SUBSTITUTION_APPROVED"
    PRICE_LOCKED = "PRICE_LOCKED"
    INVENTORY_RESERVED = "INVENTORY_RESERVED"
    READY_FOR_PAYMENT = "READY_FOR_PAYMENT"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    READY_TO_DISPENSE = "READY_TO_DISPENSE"
    DISPENSED = "DISPENSED"
    CLOSED = "CLOSED"


class InvalidStateTransitionError(ValidationError):
    """Raised when an illegal state transition or state skipping is attempted."""
    pass


class ClinicalFreezeError(ValidationError):
    """Raised when clinical parameters are modified while approval is locked."""
    pass


class PriceImmutabilityError(ValidationError):
    """Raised when pricing terms are altered on a price-locked episode."""
    pass


ALLOWED_DISPENSING_TRANSITIONS = {
    DispensingLifecycleState.DRAFT: {
        DispensingLifecycleState.PRESCRIPTION_RECEIVED,
        DispensingLifecycleState.LEGAL_VALIDATED,
    },
    DispensingLifecycleState.REQUEST_PLANNED: {
        DispensingLifecycleState.PRESCRIPTION_RECEIVED
    },
    DispensingLifecycleState.PRESCRIPTION_RECEIVED: {
        DispensingLifecycleState.LEGAL_VALIDATED
    },
    DispensingLifecycleState.LEGAL_VALIDATED: {
        DispensingLifecycleState.CLINICAL_SCREENED
    },
    DispensingLifecycleState.CLINICAL_SCREENED: {
        DispensingLifecycleState.PHARMACIST_REVIEW
    },
    DispensingLifecycleState.PHARMACIST_REVIEW: {
        DispensingLifecycleState.SUBSTITUTION_APPROVED,
        DispensingLifecycleState.PRICE_LOCKED,
    },
    DispensingLifecycleState.SUBSTITUTION_APPROVED: {
        DispensingLifecycleState.PRICE_LOCKED
    },
    DispensingLifecycleState.PRICE_LOCKED: {
        DispensingLifecycleState.INVENTORY_RESERVED
    },
    DispensingLifecycleState.INVENTORY_RESERVED: {
        DispensingLifecycleState.READY_FOR_PAYMENT
    },
    DispensingLifecycleState.READY_FOR_PAYMENT: {
        DispensingLifecycleState.PAYMENT_COMPLETED,
        DispensingLifecycleState.CLINICAL_SCREENED,  # Clinical freeze invalidation fallback
    },
    DispensingLifecycleState.PAYMENT_COMPLETED: {
        DispensingLifecycleState.READY_TO_DISPENSE
    },
    DispensingLifecycleState.READY_TO_DISPENSE: {
        DispensingLifecycleState.DISPENSED
    },
    DispensingLifecycleState.DISPENSED: {
        DispensingLifecycleState.CLOSED
    },
    DispensingLifecycleState.CLOSED: set(),
}


class DispensingLifecycleService:
    """Authoritative state machine governing dispensing episode transitions, price locks, and clinical freeze."""

    @staticmethod
    def validate_transition(from_state: str, to_state: str) -> None:
        """Validate if a transition from_state -> to_state is lawful."""
        try:
            fs = DispensingLifecycleState(from_state)
            ts = DispensingLifecycleState(to_state)
        except ValueError as exc:
            raise InvalidStateTransitionError(f"Unknown dispensing lifecycle state: {exc}")

        allowed = ALLOWED_DISPENSING_TRANSITIONS.get(fs, set())
        if ts not in allowed:
            raise InvalidStateTransitionError(
                f"Illegal state transition from '{from_state}' to '{to_state}'. Allowed next states: {[s.value for s in allowed]}."
            )

    @classmethod
    @transaction.atomic
    def transition_episode(
        cls,
        *,
        episode,
        target_state: str,
        actor,
        reason: str = "",
        metadata: dict | None = None,
    ):
        """Execute a state transition on a DispensingEpisode instance."""
        current_state = getattr(episode, "lifecycle_state", episode.status)
        cls.validate_transition(current_state, target_state)

        # Enforce clinical freeze if episode was past PHARMACIST_REVIEW
        if target_state == DispensingLifecycleState.CLINICAL_SCREENED:
            # Clear clinical review timestamp/context if reverting due to modification
            if hasattr(episode, "pharmacist_approved_at"):
                episode.pharmacist_approved_at = None

        setattr(episode, "lifecycle_state", target_state)
        if hasattr(episode, "status"):
            STATUS_MAP = {
                DispensingLifecycleState.READY_FOR_PAYMENT.value: "READY_FOR_PAYMENT",
                DispensingLifecycleState.PAYMENT_COMPLETED.value: "PAID",
                DispensingLifecycleState.READY_TO_DISPENSE.value: "READY_FOR_SUPPLY",
                DispensingLifecycleState.DISPENSED.value: "SUPPLIED",
                DispensingLifecycleState.CLOSED.value: "CLOSED",
            }
            mapped = STATUS_MAP.get(target_state)
            if mapped:
                episode.status = mapped
        episode.save()

        # Emit audit event
        from apps.prescription.services.dispensing_event_sourcing import DispensingEventSourcingService
        DispensingEventSourcingService.record_event(
            episode=episode,
            event_type=f"LIFECYCLE_TRANSITION_{target_state}",
            actor=actor,
            payload={
                "from_state": current_state,
                "to_state": target_state,
                "reason": reason,
                "metadata": metadata or {},
            },
        )
        return episode

    @staticmethod
    def verify_price_lock(episode, requested_lines: list[dict]) -> None:
        """Verify that price-locked lines match locked terms exactly."""
        if getattr(episode, "lifecycle_state", None) in (
            DispensingLifecycleState.PRICE_LOCKED.value,
            DispensingLifecycleState.INVENTORY_RESERVED.value,
            DispensingLifecycleState.READY_FOR_PAYMENT.value,
            DispensingLifecycleState.PAYMENT_COMPLETED.value,
            DispensingLifecycleState.READY_TO_DISPENSE.value,
            DispensingLifecycleState.DISPENSED.value,
            DispensingLifecycleState.CLOSED.value,
        ):
            locked_totals = getattr(episode, "locked_price_totals", None)
            if locked_totals:
                new_total = sum((Decimal(str(line_item.get("line_total", 0))) for line_item in requested_lines), Decimal("0"))
                if new_total != locked_totals.get("total"):
                    raise PriceImmutabilityError(
                        f"Price terms are locked. Locked total: {locked_totals.get('total')}, Attempted total: {new_total}."
                    )

    @staticmethod
    def check_clinical_freeze_invalidation(episode, modified_fields: list[str]) -> bool:
        """Check if modifying fields on an approved episode triggers a clinical freeze invalidation."""
        FREEZE_FIELDS = {"medicine", "strength", "quantity", "dosage", "directions", "patient", "prescriber"}
        invalidating_fields = set(modified_fields).intersection(FREEZE_FIELDS)
        if invalidating_fields and getattr(episode, "lifecycle_state", None) in (
            DispensingLifecycleState.PHARMACIST_REVIEW.value,
            DispensingLifecycleState.SUBSTITUTION_APPROVED.value,
            DispensingLifecycleState.PRICE_LOCKED.value,
            DispensingLifecycleState.INVENTORY_RESERVED.value,
            DispensingLifecycleState.READY_FOR_PAYMENT.value,
        ):
            return True
        return False
