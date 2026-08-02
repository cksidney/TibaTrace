"""Integration platform API views.

All Platform Owner surfaces. No tenant-facing integration management.
Providers cannot be activated without explicit Platform Owner state advance.
"""
from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.audit.service import log_audit
from apps.integrations.models import (
    ActivationState,
    IntegrationDeadLetter,
    IntegrationMessage,
    ProviderActivationDecision,
    ProviderActivationRequest,
    ProviderConfiguration,
    ProviderHealthSnapshot,
)
from apps.integrations.serializers import (
    ActivationAdvanceSerializer,
    DeadLetterReplaySerializer,
    IntegrationDeadLetterSerializer,
    IntegrationMessageSerializer,
    ProviderActivationRequestSerializer,
    ProviderConfigurationSerializer,
    ProviderHealthSnapshotSerializer,
)

logger = logging.getLogger(__name__)

# Valid activation state transitions (Platform Owner gate)
VALID_TRANSITIONS = {
    ActivationState.REQUESTED: [ActivationState.UNDER_REVIEW, ActivationState.REJECTED],
    ActivationState.UNDER_REVIEW: [ActivationState.SECURITY_REVIEW, ActivationState.SANDBOX_CONFIGURED, ActivationState.REJECTED],
    ActivationState.SECURITY_REVIEW: [ActivationState.SANDBOX_CONFIGURED, ActivationState.REJECTED],
    ActivationState.SANDBOX_CONFIGURED: [ActivationState.SANDBOX_TESTING, ActivationState.REJECTED],
    ActivationState.SANDBOX_TESTING: [ActivationState.SANDBOX_PASSED, ActivationState.SANDBOX_CONFIGURED, ActivationState.REJECTED],
    ActivationState.SANDBOX_PASSED: [ActivationState.CERTIFICATION_REVIEW, ActivationState.SECURITY_APPROVED, ActivationState.REJECTED],
    ActivationState.CERTIFICATION_REVIEW: [ActivationState.SECURITY_APPROVED, ActivationState.PRODUCTION_APPROVED, ActivationState.REJECTED],
    ActivationState.SECURITY_APPROVED: [ActivationState.PRODUCTION_APPROVED, ActivationState.REJECTED],
    ActivationState.PRODUCTION_APPROVED: [ActivationState.ACTIVE, ActivationState.REJECTED],
    ActivationState.ACTIVE: [ActivationState.SUSPENDED, ActivationState.REVOKED, ActivationState.DECOMMISSIONED],
    ActivationState.SUSPENDED: [ActivationState.ACTIVE, ActivationState.REVOKED, ActivationState.DECOMMISSIONED],
}


class ProviderConfigurationViewSet(ModelViewSet):
    """Platform Owner: manage provider configurations."""

    permission_classes = [IsAuthenticated]
    serializer_class = ProviderConfigurationSerializer
    queryset = ProviderConfiguration.all_objects.all()

    @action(detail=True, methods=["get"], url_path="health")
    def health(self, request, pk=None):
        provider = self.get_object()
        snapshots = ProviderHealthSnapshot.objects.filter(
            provider=provider
        ).order_by("-checked_at")[:10]
        return Response(ProviderHealthSnapshotSerializer(snapshots, many=True).data)

    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request, pk=None):
        provider = self.get_object()
        msgs = IntegrationMessage.all_objects.filter(
            provider=provider
        ).order_by("-created_at")[:100]
        return Response(IntegrationMessageSerializer(msgs, many=True).data)

    @action(detail=True, methods=["get"], url_path="dead-letters")
    def dead_letters(self, request, pk=None):
        provider = self.get_object()
        dlqs = IntegrationDeadLetter.objects.filter(
            message__provider=provider,
            replayed_at__isnull=True,
        ).select_related("message").order_by("-dead_lettered_at")[:50]
        return Response(IntegrationDeadLetterSerializer(dlqs, many=True).data)

    @action(detail=True, methods=["post"], url_path="test-connectivity")
    def test_connectivity(self, request, pk=None):
        """Test sandbox endpoint connectivity for this provider."""
        provider = self.get_object()
        endpoints = provider.endpoints.filter(is_active=True)
        results = []
        for ep in endpoints:
            results.append({
                "endpoint_name": ep.name,
                "base_url": ep.base_url,
                "allowed_hosts": ep.allowed_hosts,
                "is_allowed_hosts_configured": len(ep.allowed_hosts) > 0,
                "status": "TLS_ALLOW_LIST_CONFIGURED" if ep.allowed_hosts else "ALLOW_LIST_EMPTY_FAIL_CLOSED",
            })
        return Response({"provider": provider.provider_type, "endpoints": results})

    @action(detail=True, methods=["post"], url_path="enable-kill-switch")
    def enable_kill_switch(self, request, pk=None):
        """Immediately suspend all operations for this provider (Security Emergency Kill Switch)."""
        provider = self.get_object()
        reason = request.data.get("reason", "Emergency kill switch activated by Platform Owner.")
        provider.activation_state = ActivationState.SUSPENDED
        provider.suspended_at = timezone.now()
        provider.save(update_fields=["activation_state", "suspended_at", "updated_at"])

        log_audit(
            tenant_id=None,
            action="PROVIDER_KILL_SWITCH_ACTIVATED",
            model_name="ProviderConfiguration",
            object_id=provider.id,
            actor_id=request.user.id,
            metadata={"reason": reason, "provider_type": provider.provider_type},
        )
        return Response(
            {"detail": f"Kill switch activated for provider {provider.provider_type}.", "provider": ProviderConfigurationSerializer(provider).data},
            status=status.HTTP_200_OK,
        )


class ProviderActivationRequestViewSet(ModelViewSet):
    """Platform Owner: manage activation requests."""

    permission_classes = [IsAuthenticated]
    serializer_class = ProviderActivationRequestSerializer
    queryset = ProviderActivationRequest.objects.select_related("provider", "requested_by").all()

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="advance")
    def advance(self, request, pk=None):
        """Advance an activation request to the next state.

        Enforces the Platform Owner activation gate.
        Only valid transitions (as per VALID_TRANSITIONS) are allowed.
        """
        activation_req = self.get_object()
        serializer = ActivationAdvanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        to_state = serializer.validated_data["to_state"]
        notes = serializer.validated_data.get("notes", "")

        allowed = VALID_TRANSITIONS.get(activation_req.state, [])
        if to_state not in allowed:
            return Response(
                {
                    "detail": (
                        f"Cannot transition from '{activation_req.state}' to '{to_state}'. "
                        f"Allowed targets: {allowed}"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from_state = activation_req.state
        activation_req.state = to_state
        if serializer.validated_data.get("sandbox_evidence"):
            activation_req.sandbox_evidence = serializer.validated_data["sandbox_evidence"]
        activation_req.notes = notes
        activation_req.save(update_fields=["state", "sandbox_evidence", "notes", "updated_at"])

        # Update provider activation state to mirror
        provider = activation_req.provider
        provider.activation_state = to_state
        update_fields = ["activation_state", "updated_at"]
        if to_state == ActivationState.ACTIVE:
            provider.truth_label = "PPB_API_ACTIVE"  # Only when confirmed active.
            provider.activated_by = request.user
            provider.activated_at = timezone.now()
            update_fields += ["truth_label", "activated_by", "activated_at"]
        elif to_state == ActivationState.SUSPENDED:
            provider.suspended_at = timezone.now()
            update_fields.append("suspended_at")
        elif to_state == ActivationState.DECOMMISSIONED:
            provider.decommissioned_at = timezone.now()
            update_fields.append("decommissioned_at")
        provider.save(update_fields=update_fields)

        # Immutable decision record
        decision = ProviderActivationDecision.objects.create(
            activation_request=activation_req,
            decided_by=request.user,
            from_state=from_state,
            to_state=to_state,
            decision_notes=notes,
            truth_label=provider.truth_label,
        )

        log_audit(
            tenant_id=None,
            action="PROVIDER_ACTIVATION_ADVANCED",
            model_name="ProviderActivationRequest",
            object_id=activation_req.id,
            actor_id=request.user.id,
            metadata={
                "from_state": from_state,
                "to_state": to_state,
                "provider_type": provider.provider_type,
                "truth_label": provider.truth_label,
                "decision_id": str(decision.id),
            },
        )

        return Response(ProviderActivationRequestSerializer(activation_req).data)


class DeadLetterReplayView(ReadOnlyModelViewSet):
    """Platform Owner: manage dead-letter queue replay."""

    permission_classes = [IsAuthenticated]
    serializer_class = IntegrationDeadLetterSerializer
    queryset = IntegrationDeadLetter.objects.select_related("message", "replayed_by").all()

    @action(detail=True, methods=["post"], url_path="replay")
    def replay(self, request, pk=None):
        """Replay a dead-lettered message.

        Idempotent: only replays if not already replayed.
        Requires replay_notes.
        """
        serializer = DeadLetterReplaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        dlq = self.get_object()
        if dlq.replayed_at is not None:
            return Response(
                {"detail": "This dead-letter has already been replayed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dlq.replayed_at = timezone.now()
        dlq.replayed_by = request.user
        dlq.replay_notes = serializer.validated_data["replay_notes"]
        dlq.save(update_fields=["replayed_at", "replayed_by", "replay_notes"])

        # Reset message state for retry pickup
        msg = dlq.message
        msg.state = IntegrationMessage.MessageState.PENDING
        msg.next_retry_at = timezone.now()
        msg.save(update_fields=["state", "next_retry_at"])

        log_audit(
            tenant_id=getattr(getattr(msg, "tenant", None), "id", None),
            action="DEAD_LETTER_REPLAYED",
            model_name="IntegrationDeadLetter",
            object_id=dlq.id,
            actor_id=request.user.id,
            metadata={
                "message_id": str(msg.id),
                "message_type": msg.message_type,
                "provider_type": msg.provider.provider_type,
                "replay_notes": serializer.validated_data["replay_notes"],
            },
        )

        return Response(IntegrationDeadLetterSerializer(dlq).data)
