"""Integration platform serializers.

Credential values are never serialized. Only reference strings are exposed.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.integrations.models import (
    IntegrationDeadLetter,
    IntegrationMessage,
    ProviderActivationDecision,
    ProviderActivationRequest,
    ProviderConfiguration,
    ProviderCredentialReference,
    ProviderEndpoint,
    ProviderHealthSnapshot,
)


class ProviderConfigurationSerializer(serializers.ModelSerializer):
    is_operational = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProviderConfiguration
        fields = [
            "id",
            "provider_type",
            "environment",
            "display_name",
            "activation_state",
            "truth_label",
            "is_operational",
            "activated_at",
            "notes",
            "configuration",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "activation_state", "truth_label", "is_operational",
            "activated_at", "created_at", "updated_at",
        ]


class ProviderCredentialReferenceSerializer(serializers.ModelSerializer):
    """NEVER includes the actual secret value."""

    class Meta:
        model = ProviderCredentialReference
        fields = [
            "id",
            "provider",
            "credential_type",
            "reference",
            "is_configured",
            "configured_at",
        ]
        read_only_fields = ["id", "provider", "configured_at"]


class ProviderEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderEndpoint
        fields = ["id", "provider", "name", "base_url", "allowed_hosts", "is_active"]
        read_only_fields = ["id", "provider"]


class ProviderHealthSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderHealthSnapshot
        fields = [
            "id", "provider", "checked_at", "is_reachable",
            "response_time_ms", "status_code", "error_detail", "truth_label",
        ]
        read_only_fields = fields


class IntegrationMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationMessage
        fields = [
            "id", "provider", "direction", "message_type", "state",
            "payload_digest", "correlation_id", "tenant",
            "attempt_count", "next_retry_at", "delivered_at",
            "dead_lettered_at", "last_error", "created_at",
        ]
        read_only_fields = fields


class IntegrationDeadLetterSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationDeadLetter
        fields = [
            "id", "message", "dead_lettered_at", "dead_letter_reason",
            "replayed_at", "replayed_by", "replay_notes",
        ]
        read_only_fields = ["id", "message", "dead_lettered_at", "replayed_at", "replayed_by"]


class ProviderActivationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderActivationRequest
        fields = [
            "id", "provider", "requested_by", "requested_at", "state",
            "justification", "sandbox_evidence", "security_review_notes", "notes",
        ]
        read_only_fields = [
            "id", "requested_by", "requested_at", "state",
        ]


class ProviderActivationDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderActivationDecision
        fields = [
            "id", "activation_request", "decided_by", "decided_at",
            "from_state", "to_state", "decision_notes", "truth_label",
        ]
        read_only_fields = fields


class ActivationAdvanceSerializer(serializers.Serializer):
    """Input for advancing an activation request state."""
    to_state = serializers.CharField()
    notes = serializers.CharField(required=False, default="")
    sandbox_evidence = serializers.DictField(required=False, default=dict)


class DeadLetterReplaySerializer(serializers.Serializer):
    """Input for dead-letter replay."""
    replay_notes = serializers.CharField()
