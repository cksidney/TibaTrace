"""Phase 14B Notification Engine DRF Serializers."""
from __future__ import annotations

from rest_framework import serializers

from apps.notifications.models import (
    IntegrationNotification,
    NotificationRolePreference,
    RegulatoryExpiryTrack,
)


class IntegrationNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationNotification
        fields = [
            "id",
            "tenant",
            "category",
            "severity",
            "title",
            "summary",
            "payload",
            "is_read",
            "read_at",
            "is_acknowledged",
            "acknowledged_at",
            "truth_label",
            "created_at",
        ]
        read_only_fields = ["id", "truth_label", "created_at"]


class NotificationRolePreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationRolePreference
        fields = ["id", "role_code", "category", "enabled_channels", "minimum_severity", "created_at"]
        read_only_fields = ["id", "created_at"]


class RegulatoryExpiryTrackSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryExpiryTrack
        fields = [
            "id",
            "entity_type",
            "entity_id",
            "tenant",
            "display_name",
            "expires_at",
            "last_notified_interval_days",
            "is_resolved",
            "resolved_at",
            "resolution_evidence_reference",
            "truth_label",
            "created_at",
        ]
        read_only_fields = ["id", "truth_label", "created_at"]
