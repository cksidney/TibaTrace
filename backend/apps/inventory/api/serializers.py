from rest_framework import serializers

from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
)


class InventoryLocationSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = InventoryLocation
        fields = [
            "id", "branch", "branch_name", "location_code", "name",
            "location_type", "status", "cold_chain_capability",
            "controlled_drug_capability", "quarantine_capability",
            "returns_capability", "damaged_goods_capability",
            "expiry_hold_capability", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class InventoryBatchSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = InventoryBatch
        fields = [
            "id", "sku", "sku_code", "manufacturer_batch_number",
            "manufacture_date", "expiry_date", "quality_status",
            "recall_status", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class InventoryLedgerEntrySerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    batch_number = serializers.CharField(
        source="inventory_batch.manufacturer_batch_number",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = InventoryLedgerEntry
        fields = [
            "id", "branch", "location", "location_name", "sku", "sku_code",
            "inventory_batch", "batch_number", "entry_type", "quantity_delta",
            "unit", "base_quantity_delta", "transaction_timestamp",
            "effective_timestamp", "source_document_type", "source_document_id",
            "source_line_id", "idempotency_key", "actor", "reason_code",
            "notes", "created_at"
        ]
        read_only_fields = fields


class InventoryBalanceSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    sku_name = serializers.CharField(source="sku.display_name", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    batch_number = serializers.CharField(
        source="inventory_batch.manufacturer_batch_number",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = InventoryBalance
        fields = [
            "id", "branch", "location", "location_name", "sku", "sku_code",
            "sku_name", "inventory_batch", "batch_number", "quality_status",
            "expiry_status", "on_hand", "reserved", "available", "quarantined",
            "damaged", "expired", "last_calculated_at"
        ]
        read_only_fields = fields


class InventoryReservationSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    location_name = serializers.CharField(source="source_location.name", read_only=True)
    batch_number = serializers.CharField(
        source="batch.manufacturer_batch_number",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = InventoryReservation
        fields = [
            "id", "branch", "source_location", "location_name", "sku",
            "sku_code", "batch", "batch_number", "requested_quantity",
            "allocated_quantity", "purpose", "status", "expiry_time",
            "idempotency_key", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
