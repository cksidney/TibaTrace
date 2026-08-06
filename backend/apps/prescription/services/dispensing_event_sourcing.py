"""Dispensing Event Sourcing and Audit Replay Engine for Stage 2D.2.

Emits structured, immutable domain audit events for every dispensing transition and
rebuilds readiness, inventory, payment, and audit timeline projections via event replay.
"""

from __future__ import annotations

from typing import Any, Dict, List

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.service import log_audit
from apps.prescription.models import DispensingEpisode


class DispensingEventSourcingService:
    """Authoritative event sourcing and audit replay service."""

    @classmethod
    def record_event(
        cls,
        *,
        episode,
        event_type: str,
        actor=None,
        payload: dict | None = None,
    ) -> AuditEvent:
        """Record an immutable domain event for a dispensing episode transition."""
        tenant_id = getattr(episode, "tenant_id", None)
        if not tenant_id:
            # Bind every event to a tenant at append time. AuditEvent.save
            # rejects a missing tenant anyway, but failing here names the
            # aggregate rather than the column.
            raise ValidationError(
                f"Cannot record {event_type}: the dispensing episode carries no "
                "tenant, and an event without tenant binding cannot be replayed "
                "safely."
            )
        actor_id = getattr(actor, "id", None) if actor else None
        event_data = {
            "dispensing_id": str(getattr(episode, "id", "")),
            "dispensing_number": getattr(episode, "dispensing_number", ""),
            "event_type": event_type,
            "timestamp": timezone.now().isoformat(),
            **(payload or {}),
        }
        return log_audit(
            tenant_id=tenant_id,
            action=event_type,
            model_name="DispensingEpisode",
            object_id=getattr(episode, "id", None),
            actor_id=actor_id,
            metadata=event_data,
        )

    @classmethod
    def assert_replayable(cls, *, tenant_id, episode_id):
        """Refuse a replay that cannot be trusted, before any events are read.

        Ownership is checked explicitly against the aggregate rather than being
        left to the query. A cross-tenant episode id filtered out by a WHERE
        clause returns an empty stream, and an empty stream is a legitimate
        state -- an episode that has not transitioned yet. The caller cannot
        tell the two apart, so a replay of another tenant's aggregate would
        silently look like a brand-new episode.
        """
        if not tenant_id:
            raise ValidationError(
                "Dispensing event replay requires an explicit tenant. Replaying "
                "without one cannot distinguish an empty stream from an "
                "inaccessible one."
            )
        if not episode_id:
            raise ValidationError("Dispensing event replay requires an episode id.")

        # Scoped by tenant as well as pk. Deliberately one query and one
        # message: a lookup by pk alone could report "exists, but not yours",
        # which answers a question the caller has no right to ask -- it turns
        # replay into an oracle for whether an id exists in another tenant.
        # Refusing without disclosing existence is both safer and audit-clean.
        episode = DispensingEpisode.all_objects.filter(
            pk=episode_id, tenant_id=tenant_id
        ).first()
        if episode is None:
            raise ValidationError(
                f"Dispensing episode {episode_id} is not owned by tenant "
                f"{tenant_id}; replay refused. It does not exist, or it belongs "
                "to another tenant -- either way this caller may not replay it, "
                "and returning an empty stream would be indistinguishable from "
                "an aggregate that simply has no events yet."
            )
        return episode

    @classmethod
    def get_event_stream(cls, *, tenant_id, episode_id) -> List[Dict[str, Any]]:
        """Retrieve the ordered, immutable sequence of events for a dispensing episode."""
        cls.assert_replayable(tenant_id=tenant_id, episode_id=episode_id)

        # all_objects with an explicit tenant filter. `objects` is tenant-strict:
        # it filters on thread-local context that nothing sets outside a request,
        # so a replay from a command, task or test read **zero events** and the
        # projection concluded the aggregate had no history. For event sourcing
        # that is the worst possible failure -- a rebuild from an empty stream
        # produces a clean-looking initial state rather than an error.
        logs = AuditEvent.all_objects.filter(
            tenant_id=tenant_id,
            model_name="DispensingEpisode",
            object_id=episode_id,
        ).order_by("created_at", "id")

        events = []
        for log in logs:
            meta = dict(log.metadata or {})
            events.append({
                "audit_id": str(log.id),
                "action": log.action,
                "created_at": log.created_at.isoformat(),
                "actor_id": str(log.actor_id) if log.actor_id else None,
                "metadata": meta,
            })
        return events

    @classmethod
    def replay_projection(cls, *, tenant_id, episode_id) -> Dict[str, Any]:
        """Rebuild DispensingReadiness, Inventory, Payment, and Audit timeline entirely from events.

        Returns a dictionary containing the replayed state projections.
        """
        # Ownership is proven before replay; an empty stream past this point is
        # genuinely "no events yet" rather than "not visible to me".
        cls.assert_replayable(tenant_id=tenant_id, episode_id=episode_id)
        stream = cls.get_event_stream(tenant_id=tenant_id, episode_id=episode_id)

        current_lifecycle_state = "REQUEST_PLANNED"
        clinical_state = "PENDING"
        commercial_state = "PENDING"
        inventory_state = "NOT_RESERVED"
        payment_state = "NOT_REQUIRED"
        substitutions = []
        price_totals = None
        timeline = []

        for evt in stream:
            action = evt["action"]
            meta = evt["metadata"]
            timeline.append({
                "action": action,
                "timestamp": evt["created_at"],
                "actor_id": evt["actor_id"],
            })

            if action.startswith("LIFECYCLE_TRANSITION_"):
                to_state = meta.get("to_state", "")
                current_lifecycle_state = to_state

            if "PRESCRIPTION_RECEIVED" in action:
                clinical_state = "RECEIVED"
            elif "LEGAL_VALIDATED" in action:
                clinical_state = "VALIDATED"
            elif "CLINICAL_SCREENED" in action:
                clinical_state = "SCREENED"
            elif "PHARMACIST_REVIEWED" in action or "PHARMACIST_REVIEW" in action:
                clinical_state = "APPROVED"
            elif "SUBSTITUTION_APPROVED" in action:
                substitutions.append(meta.get("substitution", {}))
            elif "PRICE_LOCKED" in action:
                commercial_state = "PRICE_LOCKED"
                price_totals = meta.get("totals")
            elif "INVENTORY_RESERVED" in action:
                inventory_state = "RESERVED"
            elif "READY_FOR_PAYMENT" in action:
                commercial_state = "READY_FOR_PAYMENT"
                payment_state = "PENDING"
            elif "PAYMENT_COMPLETED" in action:
                commercial_state = "PAID"
                payment_state = "PAID"
            elif "PAYMENT_FAILED" in action or "PAYMENT_REVERSED" in action:
                payment_state = "FAILED" if "FAILED" in action else "REVERSED"
            elif "DISPENSED" in action:
                clinical_state = "DISPENSED"
                inventory_state = "DISPENSED"

        return {
            "replayed_lifecycle_state": current_lifecycle_state,
            "replayed_clinical_state": clinical_state,
            "replayed_commercial_state": commercial_state,
            "replayed_inventory_state": inventory_state,
            "replayed_payment_state": payment_state,
            "replayed_substitutions": substitutions,
            "replayed_price_totals": price_totals,
            "event_count": len(stream),
            "timeline": timeline,
        }
