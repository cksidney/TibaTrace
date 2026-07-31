from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.core.money import format_decimal, format_money
from apps.pos_transactions.models import (
    PosTransaction,
    PosTransactionInventoryContext,
    PosTransactionLine,
)


class MoneyField(serializers.Field):
    def to_representation(self, value):
        if value is None:
            return None
        return format_money(value)


class PosTransactionInventoryContextSerializer(serializers.ModelSerializer):
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = PosTransactionInventoryContext
        fields = ["store", "available_quantity", "stock_state", "policy"]

    def get_available_quantity(self, row):
        return format_decimal(row.available_quantity, places=2)


class PosTransactionLineSerializer(serializers.ModelSerializer):
    unit_price = MoneyField()
    discount_amount = MoneyField()
    tax_amount = MoneyField()
    line_total = MoneyField()
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    inventory_context = PosTransactionInventoryContextSerializer(read_only=True)

    class Meta:
        model = PosTransactionLine
        fields = [
            "id", "sku", "sku_code", "description_snapshot", "unit", "quantity",
            "unit_price", "discount_amount", "tax_amount", "line_total", "currency",
            "price_snapshot", "scan_source", "inventory_context",
        ]


class PosTransactionSerializer(serializers.ModelSerializer):
    subtotal = MoneyField()
    discount_total = MoneyField()
    tax_total = MoneyField()
    total = MoneyField()
    branch_code = serializers.CharField(source="branch.code", read_only=True)
    register_code = serializers.CharField(source="register.code", read_only=True)
    operator_username = serializers.CharField(source="operator.username", read_only=True)
    lines = PosTransactionLineSerializer(many=True, read_only=True)

    class Meta:
        model = PosTransaction
        fields = [
            "id", "transaction_number", "state", "channel", "branch", "branch_code",
            "store", "register", "register_code", "register_session", "operator_shift",
            "business_day", "operator", "operator_username", "device_id", "customer", "patient",
            "currency", "subtotal", "discount_total", "tax_total", "total", "hold_reason",
            "held_at", "cancelled_at", "cancellation_reason", "created_at", "updated_at", "lines",
        ]


class CreateDraftRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    store_id = serializers.UUIDField()
    customer_id = serializers.UUIDField(required=False, allow_null=True)
    patient_id = serializers.UUIDField(required=False, allow_null=True)


class CatalogueSearchRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    store_id = serializers.UUIDField()
    query = serializers.CharField(max_length=255)
    customer_id = serializers.UUIDField(required=False, allow_null=True)


class AddLineRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    sku_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.0001"))


class ScanRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    barcode = serializers.CharField(max_length=255)
    quantity = serializers.DecimalField(
        max_digits=15, decimal_places=4, min_value=Decimal("0.0001"), default=Decimal("1")
    )


class SetQuantityRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    line_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.0001"))


class RemoveLineRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    line_id = serializers.UUIDField()


class DeviceActionRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)


class HoldRequestSerializer(DeviceActionRequestSerializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CancelRequestSerializer(DeviceActionRequestSerializer):
    reason = serializers.CharField()


class RetailCatalogueItemSerializer(serializers.Serializer):
    sku_id = serializers.UUIDField(source="sku.pk")
    sku_code = serializers.CharField(source="sku.sku_code")
    display_name = serializers.CharField(source="sku.display_name")
    unit = serializers.CharField(source="sku.package_definition.unit_of_measure")
    stock_tracking_required = serializers.BooleanField(source="sku.stock_tracking_required")
    available_quantity = serializers.DecimalField(max_digits=15, decimal_places=4)
    stock_state = serializers.CharField()
    unit_price = serializers.DecimalField(source="resolved_price.unit_price", max_digits=15, decimal_places=2)
    currency = serializers.CharField(source="resolved_price.currency")
    price_source = serializers.CharField(source="resolved_price.source")
    price_reference = serializers.CharField(source="resolved_price.reference")
