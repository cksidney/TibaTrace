from rest_framework import serializers

from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
)


class InventoryLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryLocation
        fields = [
            "id", "branch", "name", "location_type", "status", 
            "quarantine_capability", "damaged_goods_capability", 
            "expiry_hold_capability", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class InventoryBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryBatch
        fields = [
            "id", "manufacturer_batch_number", "manufacture_date", "expiry_date", 
            "quality_status", "recall_status", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class InventoryLedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryLedgerEntry
        fields = [
            "id", "branch", "location", "sku", "inventory_batch", 
            "entry_type", "quantity_delta", "unit", "base_quantity_delta", 
            "transaction_timestamp", "effective_timestamp", "source_document_type", 
            "source_document_id", "source_line_id", "idempotency_key", 
            "actor", "reason_code", "created_at"
        ]
        read_only_fields = fields

class InventoryBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryBalance
        fields = [
            "id", "branch", "location", "sku", "inventory_batch", 
            "quality_status", "expiry_status", "on_hand", "reserved", 
            "available", "quarantined", "damaged", "expired", 
            "last_calculated_at"
        ]
        read_only_fields = fields

class InventoryReservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryReservation
        fields = [
            "id", "branch", "source_location", "sku", "batch", 
            "requested_quantity", "allocated_quantity", "purpose", "status", 
            "expiry_time", "idempotency_key", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
