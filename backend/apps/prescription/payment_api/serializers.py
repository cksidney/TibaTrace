from decimal import Decimal

from rest_framework import serializers

from apps.prescription.payment_models import (
    TENDER_TYPES,
    PaymentIntent,
    PaymentSettlement,
    PaymentTender,
)


class PaymentTenderSerializer(serializers.ModelSerializer):
    effective_settled = serializers.SerializerMethodField()

    class Meta:
        model = PaymentTender
        fields = [
            "id",
            "tender_type",
            "provider",
            "allocated_amount",
            "settled_amount",
            "reversed_amount",
            "effective_settled",
            "cash_received",
            "change_due",
            "external_reference",
            "status",
        ]
        # Financial state moves only through the services below.
        read_only_fields = fields

    def get_effective_settled(self, tender):
        return str(tender.effective_settled)


class PaymentIntentSerializer(serializers.ModelSerializer):
    tenders = serializers.SerializerMethodField()
    amount_remaining = serializers.SerializerMethodField()
    effective_settled = serializers.SerializerMethodField()

    class Meta:
        model = PaymentIntent
        fields = [
            "id",
            "dispensing_episode",
            "currency",
            "amount_due",
            "amount_settled",
            "amount_reversed",
            "effective_settled",
            "amount_remaining",
            "status",
            "version",
            "tenders",
        ]
        read_only_fields = fields

    def get_tenders(self, intent):
        return PaymentTenderSerializer(
            PaymentTender.all_objects.filter(payment_intent=intent).order_by("created_at"),
            many=True,
        ).data

    def get_amount_remaining(self, intent):
        return str(intent.amount_remaining)

    def get_effective_settled(self, intent):
        return str(intent.effective_settled)


class CreateIntentSerializer(serializers.Serializer):
    dispensing_episode_id = serializers.UUIDField()
    amount_due = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal("0"))
    currency = serializers.CharField(max_length=3, default="KES")
    device_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    register_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=255)


class AllocateTenderSerializer(serializers.Serializer):
    tender_type = serializers.ChoiceField(choices=[code for code, _ in TENDER_TYPES])
    allocated_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    provider = serializers.CharField(max_length=20, required=False, default="MANUAL")
    idempotency_key = serializers.CharField(max_length=255)


class CashSettleSerializer(serializers.Serializer):
    cash_received = serializers.DecimalField(max_digits=15, decimal_places=2)
    register_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=255)


class CardConfirmSerializer(serializers.Serializer):
    approval_reference = serializers.CharField(max_length=255)
    approved_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    idempotency_key = serializers.CharField(max_length=255)


class InitiateProviderSerializer(serializers.Serializer):
    provider = serializers.CharField(max_length=20, default="FAKE")


class ReverseSettlementSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    reason = serializers.CharField(max_length=500)
    idempotency_key = serializers.CharField(max_length=255)


class PaymentSettlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentSettlement
        fields = [
            "id",
            "payment_tender",
            "amount",
            "currency",
            "provider_reference",
            "source",
            "settled_at",
        ]
        read_only_fields = fields
