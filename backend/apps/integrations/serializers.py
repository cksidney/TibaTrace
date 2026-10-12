"""Integration platform serializers.

Credential values are never serialized. Only reference strings are exposed.
"""
from __future__ import annotations

import re

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
    latest_health = serializers.SerializerMethodField()
    endpoints = serializers.SerializerMethodField()
    credential_references = serializers.SerializerMethodField()

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
            "latest_health",
            "endpoints",
            "credential_references",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "activation_state", "truth_label", "is_operational",
            "activated_at", "created_at", "updated_at",
            "latest_health", "endpoints", "credential_references",
        ]

    def get_latest_health(self, obj):
        snapshot = next(iter(obj.health_snapshots.all()), None)
        return ProviderHealthSnapshotSerializer(snapshot).data if snapshot else None

    def get_endpoints(self, obj):
        return ProviderEndpointSerializer(obj.endpoints.all(), many=True).data

    def get_credential_references(self, obj):
        return ProviderCredentialReferenceSerializer(obj.credential_references.all(), many=True).data

    def validate_configuration(self, value):
        blocked = re.compile(r"secret|password|token|private.?key|credential.?value", re.IGNORECASE)

        def inspect(item, path="configuration"):
            if isinstance(item, dict):
                for key, child in item.items():
                    if blocked.search(str(key)):
                        raise serializers.ValidationError(
                            f"{path}.{key} looks like a secret field. Store only secret-manager references."
                        )
                    inspect(child, f"{path}.{key}")
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    inspect(child, f"{path}[{index}]")

        inspect(value)
        return value


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
    requested_by_name = serializers.SerializerMethodField()
    decisions = serializers.SerializerMethodField()

    class Meta:
        model = ProviderActivationRequest
        fields = [
            "id", "provider", "requested_by", "requested_by_name", "requested_at", "state",
            "justification", "sandbox_evidence", "security_review_notes", "notes", "decisions",
        ]
        read_only_fields = [
            "id", "requested_by", "requested_at", "state",
        ]

    def get_requested_by_name(self, obj):
        full_name = obj.requested_by.get_full_name().strip()
        return full_name or obj.requested_by.get_username()

    def get_decisions(self, obj):
        return ProviderActivationDecisionSerializer(obj.decisions.all(), many=True).data

    def validate_justification(self, value):
        cleaned = value.strip()
        if len(cleaned) < 15:
            raise serializers.ValidationError("Enter a business justification of at least 15 characters.")
        return cleaned

    def validate(self, attrs):
        if self.instance is not None:
            return attrs
        provider = attrs.get("provider")
        if provider and provider.activation_requests.exclude(
            state__in=["REJECTED", "REVOKED", "DECOMMISSIONED"]
        ).exists():
            raise serializers.ValidationError({
                "provider": "This provider already has an activation request in progress or active."
            })
        return attrs


class ProviderActivationDecisionSerializer(serializers.ModelSerializer):
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ProviderActivationDecision
        fields = [
            "id", "activation_request", "decided_by", "decided_by_name", "decided_at",
            "from_state", "to_state", "decision_notes", "truth_label",
        ]
        read_only_fields = fields

    def get_decided_by_name(self, obj):
        full_name = obj.decided_by.get_full_name().strip()
        return full_name or obj.decided_by.get_username()


class ActivationAdvanceSerializer(serializers.Serializer):
    """Input for advancing an activation request state."""
    to_state = serializers.CharField()
    notes = serializers.CharField(required=False, default="")
    sandbox_evidence = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        notes = attrs.get("notes", "").strip()
        if len(notes) < 10:
            raise serializers.ValidationError({"notes": "Record at least 10 characters explaining the review and decision."})

        evidence_required_states = {
            "SANDBOX_PASSED",
            "SECURITY_APPROVED",
            "PRODUCTION_APPROVED",
            "ACTIVE",
        }
        if attrs.get("to_state") in evidence_required_states:
            evidence = attrs.get("sandbox_evidence") or {}
            reference = str(evidence.get("evidence_reference", "")).strip()
            if not reference:
                raise serializers.ValidationError({
                    "sandbox_evidence": "Include an evidence_reference for this approval transition."
                })
        return attrs


class DeadLetterReplaySerializer(serializers.Serializer):
    """Input for dead-letter replay."""
    replay_notes = serializers.CharField()
