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


class RegulatoryTenantImpactSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryTenantImpact
        fields = [
            "id", "alert", "tenant", "state",
            "quarantined_at", "affected_batches",
            "quarantined_stock_count",
            "prior_dispense_trace_required",
            "prior_dispense_patient_count",
            "notes", "created_at",
        ]
        read_only_fields = fields


class RegulatoryActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryAction
        fields = [
            "id", "impact", "action_type",
            "performed_by", "performed_at",
            "notes", "evidence_payload",
        ]
        read_only_fields = ["id", "performed_by", "performed_at"]


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
