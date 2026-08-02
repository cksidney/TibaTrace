"""Premises verification serializers for the NIF API.

Truth label: MANUAL_INTERNAL_VERIFICATION.
Never exposes submitted_by email or sensitive reviewer notes to tenant roles.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.pharmacy_network.models import (
    PremisesVerificationRequest,
    PremisesVerificationSnapshot,
)


class PremisesVerificationRequestListSerializer(serializers.ModelSerializer):
    """Safe list view for tenant and HQ use."""

    class Meta:
        model = PremisesVerificationRequest
        fields = [
            "id",
            "state",
            "submitted_at",
            "reviewed_at",
            "truth_label",
            "created_at",
        ]
        read_only_fields = fields


class PremisesVerificationRequestDetailSerializer(serializers.ModelSerializer):
    """Full detail view for Platform Owner / Compliance."""

    class Meta:
        model = PremisesVerificationRequest
        fields = [
            "id",
            "tenant",
            "pharmacy_profile",
            "state",
            "submitted_by",
            "submitted_at",
            "reviewed_by",
            "reviewed_at",
            "reviewer_notes",
            "verifier_declaration",
            "evidence_payload",
            "truth_label",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PremisesVerificationSubmitSerializer(serializers.Serializer):
    """Input for tenant evidence submission."""
    pharmacy_profile_id = serializers.IntegerField()
    evidence_payload = serializers.DictField(default=dict)


class PremisesVerificationReviewSerializer(serializers.Serializer):
    """Input for Platform Owner review decisions."""
    action = serializers.ChoiceField(choices=["approve", "reject", "request_clarification", "suspend", "revoke"])
    reviewer_notes = serializers.CharField(required=False, default="")
    verifier_declaration = serializers.CharField(required=False, default="")


class PremisesVerificationSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = PremisesVerificationSnapshot
        fields = [
            "id",
            "verification_request",
            "captured_state",
            "declared_licence_number",
            "declared_expiry",
            "declared_superintendent",
            "truth_label",
            "captured_at",
        ]
        read_only_fields = fields
