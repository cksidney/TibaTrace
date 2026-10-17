"""Serializers for Taxation & KRA eTIMS API."""
from __future__ import annotations

from rest_framework import serializers

from apps.taxation.models import FiscalReceipt, FiscalSubmissionLog, TenantEtimsProfile


class TenantEtimsProfileSerializer(serializers.ModelSerializer):
    cm_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Communication AES key (write-only; never exposed in GET responses).",
    )
    has_cm_key = serializers.SerializerMethodField()
    is_configured = serializers.BooleanField(read_only=True)

    class Meta:
        model = TenantEtimsProfile
        fields = [
            "id",
            "is_enabled",
            "environment",
            "tin",
            "bhf_id",
            "dvc_srl_no",
            "cm_key",
            "has_cm_key",
            "base_url",
            "taxpayer_name",
            "branch_name",
            "sdc_id",
            "mrc_no",
            "last_invoice_number",
            "last_credit_note_number",
            "auto_fiscalize_pos_sales",
            "is_initialized",
            "is_configured",
            "last_sync_at",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "sdc_id",
            "mrc_no",
            "last_invoice_number",
            "last_credit_note_number",
            "is_initialized",
            "is_configured",
            "last_sync_at",
            "created_at",
            "updated_at",
        ]

    def get_has_cm_key(self, obj: TenantEtimsProfile) -> bool:
        return bool(obj.cm_key)

    def update(self, instance: TenantEtimsProfile, validated_data: dict) -> TenantEtimsProfile:
        cm_key = validated_data.pop("cm_key", None)
        if cm_key:
            instance.cm_key = cm_key
        return super().update(instance, validated_data)


class FiscalReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalReceipt
        fields = [
            "id",
            "receipt_type",
            "invoice_number",
            "original_invoice_number",
            "sales_type_code",
            "receipt_type_code",
            "payment_type_code",
            "customer_pin",
            "customer_name",
            "customer_mobile",
            "taxable_amount_a",
            "tax_amount_a",
            "taxable_amount_b",
            "tax_amount_b",
            "taxable_amount_c",
            "tax_amount_c",
            "taxable_amount_d",
            "tax_amount_d",
            "taxable_amount_e",
            "tax_amount_e",
            "total_taxable_amount",
            "total_tax_amount",
            "total_amount",
            "currency",
            "internal_data",
            "receipt_signature",
            "qr_code_url",
            "qr_code_image_data",
            "submission_status",
            "attempt_count",
            "last_error",
            "submitted_at",
            "items_snapshot",
            "created_at",
        ]
        read_only_fields = fields


class FiscalSubmissionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalSubmissionLog
        fields = [
            "id",
            "fiscal_receipt",
            "endpoint",
            "status_code",
            "success",
            "response_time_ms",
            "error_message",
            "response_payload",
            "created_at",
        ]
        read_only_fields = fields
