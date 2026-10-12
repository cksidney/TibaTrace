"""Regulatory alert and recall serializers."""
from __future__ import annotations

from rest_framework import serializers

from apps.inventory.recalls.models import (
    RegulatoryAction,
    RegulatoryAlert,
    RegulatoryAlertVersion,
    RegulatoryClosure,
    RegulatoryMatchCandidate,
    RegulatoryTenantImpact,
)


class RegulatoryAlertListSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryAlert
        fields = [
            "id", "alert_reference", "title", "severity", "status",
            "issuing_regulator", "regulator_issue_date",
            "ppb_registration_number", "gtin", "product_name",
            "truth_label", "ingested_at",
        ]
        read_only_fields = fields


class RegulatoryAlertDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryAlert
        fields = [
            "id", "alert_reference", "title", "severity", "status",
            "issuing_regulator", "regulator_issue_date",
            "ppb_registration_number", "gtin", "product_name",
            "manufacturer_name", "affected_batches",
            "description", "recommended_action",
            "truth_label", "ingested_by", "ingested_at",
            "activated_by", "activated_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class RegulatoryAlertIngestSerializer(serializers.Serializer):
    """Input for Platform Owner alert ingestion."""
    alert_reference = serializers.CharField(max_length=100)
    title = serializers.CharField(max_length=300)
    severity = serializers.ChoiceField(choices=["CRITICAL", "HIGH", "MEDIUM", "LOW"])
    issuing_regulator = serializers.CharField(required=False, default="PPB", max_length=80)
    ppb_registration_number = serializers.CharField(required=False, default="")
    gtin = serializers.CharField(required=False, default="")
    product_name = serializers.CharField(required=False, default="")
    manufacturer_name = serializers.CharField(required=False, default="")
    affected_batches = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    description = serializers.CharField(required=False, default="")
    recommended_action = serializers.CharField(required=False, default="")
    regulator_issue_date = serializers.DateField(required=False, allow_null=True)

    def validate_gtin(self, value):
        if not value:
            return value
        if len(value) != 14 or not value.isdigit():
            raise serializers.ValidationError("GTIN must contain exactly 14 numeric digits.")
        digits = [int(digit) for digit in value[:-1]]
        check_digit = int(value[-1])
        total = sum(
            digit * (3 if offset % 2 == 0 else 1)
            for offset, digit in enumerate(reversed(digits))
        )
        expected = (10 - total % 10) % 10
        if expected != check_digit:
            raise serializers.ValidationError("GTIN check digit is invalid.")
        return value


class RegulatoryTenantImpactSerializer(serializers.ModelSerializer):
    alert_reference = serializers.CharField(source="alert.alert_reference", read_only=True)
    alert_title = serializers.CharField(source="alert.title", read_only=True)
    alert_severity = serializers.CharField(source="alert.severity", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = RegulatoryTenantImpact
        fields = [
            "id", "alert", "alert_reference", "alert_title", "alert_severity",
            "tenant", "tenant_name", "state",
            "quarantined_at", "affected_batches",
            "quarantined_stock_count",
            "prior_dispense_trace_required",
            "prior_dispense_patient_count", "notes", "actions", "created_at",
        ]
        read_only_fields = fields

    def get_actions(self, impact):
        return RegulatoryActionReadSerializer(impact.actions.select_related("performed_by"), many=True).data


class RegulatoryActionReadSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(source="performed_by.get_username", read_only=True)

    class Meta:
        model = RegulatoryAction
        fields = [
            "id", "impact", "action_type", "performed_at",
            "performed_by_name", "notes", "evidence_payload",
        ]
        read_only_fields = fields


class RegulatoryQuarantineSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField()
    affected_batches = serializers.ListField(
        child=serializers.CharField(max_length=100, allow_blank=False),
        allow_empty=False,
    )
    prior_dispense_trace_required = serializers.BooleanField(required=False, default=False)


class RegulatoryTenantQuarantineSerializer(serializers.Serializer):
    affected_batches = serializers.ListField(
        child=serializers.CharField(max_length=100, allow_blank=False),
        allow_empty=False,
    )
    prior_dispense_trace_required = serializers.BooleanField(required=False, default=False)


class RegulatoryActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryAction
        fields = [
            "id", "impact", "action_type",
            "performed_by", "performed_at",
            "notes", "evidence_payload",
        ]
        read_only_fields = ["id", "performed_by", "performed_at"]


class RegulatoryActionCreateSerializer(serializers.Serializer):
    action_type = serializers.ChoiceField(choices=RegulatoryAction.ActionType.choices)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    evidence_payload = serializers.DictField(required=False, default=dict)


class RegulatoryAlertVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryAlertVersion
        fields = ["id", "alert", "version_number", "snapshot", "captured_at"]
        read_only_fields = fields


class RegulatoryClosureSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryClosure
        fields = [
            "id", "impact", "closed_by", "closed_at",
            "regulator_withdrawal_reference",
            "compliance_review_notes", "truth_label",
        ]
        read_only_fields = fields


class RegulatoryClosureCreateSerializer(serializers.Serializer):
    """Input for closing a tenant regulatory impact."""
    regulator_withdrawal_reference = serializers.CharField()
    compliance_review_notes = serializers.CharField()


class RegulatoryMatchCandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryMatchCandidate
        fields = [
            "id", "alert", "medicine_code",
            "ppb_registration_number", "gtin", "batch_number",
            "confidence_tier", "requires_manual_review",
            "reviewed_by", "reviewed_at", "is_confirmed",
        ]
        read_only_fields = ["id", "alert", "confidence_tier", "reviewed_by", "reviewed_at"]
