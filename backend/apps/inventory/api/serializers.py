from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
    StocktakeCount,
    StocktakeSession,
    StockTransfer,
    StockTransferLine,
)


class StocktakeCountSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    sku_name = serializers.CharField(source="sku.display_name", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    batch_number = serializers.CharField(
        source="batch.manufacturer_batch_number", read_only=True, allow_null=True
    )

    class Meta:
        model = StocktakeCount
        fields = [
            "id", "location", "location_name", "sku", "sku_code", "sku_name",
            "batch", "batch_number", "expected_quantity", "counted_quantity",
            "variance", "reason", "counter", "timestamp",
            "first_count", "recount", "final_approved_count", "voided", "void_reason", "voided_at", "updated_at",
        ]


class StocktakeSessionSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    locations = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True, allow_null=True)
    approved_by_username = serializers.CharField(source="approved_by.username", read_only=True, allow_null=True)
    counts = StocktakeCountSerializer(many=True, read_only=True)
    completeness = serializers.SerializerMethodField()

    def get_completeness(self, obj):
        from apps.inventory.services import StocktakeService

        return StocktakeService.completeness(obj)

    class Meta:
        model = StocktakeSession
        fields = [
            "id", "branch", "branch_name", "locations", "scope", "status",
            "document_number", "start_time", "end_time", "created_by_username",
            "approved_by_username", "counts", "created_at", "updated_at",
            "scope_snapshot", "empty_location_confirmations", "cancellation_reason", "completeness",
        ]


class StocktakeOpenSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    location_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)
    scope = serializers.ChoiceField(choices=["FULL", "PARTIAL", "CYCLE"], default="PARTIAL")
    document_number = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_location_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Choose each count location only once.")
        return value


class StocktakeCountInputSerializer(serializers.Serializer):
    location_id = serializers.UUIDField()
    sku_id = serializers.UUIDField()
    batch_id = serializers.UUIDField(required=False, allow_null=True)
    counted_quantity = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=0)
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class StocktakeRevisionInputSerializer(serializers.Serializer):
    count_id = serializers.UUIDField()
    counted_quantity = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=0, required=False)
    reason = serializers.CharField(max_length=1000, allow_blank=False)
    expected_updated_at = serializers.DateTimeField()
    idempotency_key = serializers.CharField(max_length=128, allow_blank=False)


class StocktakeReasonInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, allow_blank=False)


class StocktakeEmptyLocationInputSerializer(StocktakeReasonInputSerializer):
    location_id = serializers.UUIDField()


class InventoryLocationSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = InventoryLocation
        fields = [
            "id",
            "branch",
            "branch_name",
            "location_code",
            "name",
            "location_type",
            "status",
            "cold_chain_capability",
            "controlled_drug_capability",
            "quarantine_capability",
            "returns_capability",
            "damaged_goods_capability",
            "expiry_hold_capability",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class InventoryLocationProvisionSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    location_code = serializers.CharField(max_length=100)
    name = serializers.CharField(max_length=255)
    location_type = serializers.ChoiceField(
        choices=InventoryLocation.LocationType.choices,
        default=InventoryLocation.LocationType.STORE,
    )


class InventoryBatchSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = InventoryBatch
        fields = [
            "id",
            "sku",
            "sku_code",
            "manufacturer_batch_number",
            "lot_kind",
            "manufacture_date",
            "expiry_date",
            "quality_status",
            "recall_status",
            "created_at",
            "updated_at",
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
            "id",
            "branch",
            "location",
            "location_name",
            "sku",
            "sku_code",
            "inventory_batch",
            "batch_number",
            "entry_type",
            "quantity_delta",
            "unit",
            "base_quantity_delta",
            "transaction_timestamp",
            "effective_timestamp",
            "source_document_type",
            "source_document_id",
            "source_line_id",
            "idempotency_key",
            "actor",
            "reason_code",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


class InventoryBalanceSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    sku_barcode = serializers.CharField(source="sku.default_barcode", read_only=True)
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
            "id",
            "branch",
            "location",
            "location_name",
            "sku",
            "sku_code",
            "sku_barcode",
            "sku_name",
            "inventory_batch",
            "batch_number",
            "quality_status",
            "expiry_status",
            "on_hand",
            "reserved",
            "available",
            "quarantined",
            "damaged",
            "expired",
            "last_calculated_at",
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
            "id",
            "branch",
            "source_location",
            "location_name",
            "sku",
            "sku_code",
            "batch",
            "batch_number",
            "requested_quantity",
            "allocated_quantity",
            "purpose",
            "status",
            "expiry_time",
            "idempotency_key",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class StockTransferLineSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    sku_barcode = serializers.CharField(source="sku.default_barcode", read_only=True)
    sku_name = serializers.CharField(source="sku.display_name", read_only=True)
    batch_number = serializers.CharField(
        source="batch.manufacturer_batch_number",
        read_only=True,
        allow_null=True,
    )
    dispatch_allocations = serializers.SerializerMethodField()

    def get_dispatch_allocations(self, line):
        allocations = (
            InventoryLedgerEntry.all_objects.filter(
                tenant=line.tenant,
                source_document_type="STOCK_TRANSFER",
                source_document_id=str(line.transfer_id),
                source_line_id=str(line.pk),
                entry_type=InventoryLedgerEntry.EntryType.TRANSFER_OUT,
            )
            .values(
                "inventory_batch_id",
                "inventory_batch__manufacturer_batch_number",
            )
            .annotate(total=Sum("base_quantity_delta"))
            .order_by("inventory_batch__expiry_date")
        )
        result = []
        for allocation in allocations:
            batch_id = allocation["inventory_batch_id"]
            if not batch_id:
                continue
            receipts = InventoryLedgerEntry.all_objects.filter(
                tenant=line.tenant,
                source_document_type="STOCK_TRANSFER",
                source_document_id=str(line.transfer_id),
                source_line_id=str(line.pk),
                inventory_batch_id=batch_id,
                entry_type=InventoryLedgerEntry.EntryType.TRANSFER_IN,
            )
            accepted = receipts.filter(reason_code="TRANSFER_RECEIPT").aggregate(total=Sum("base_quantity_delta"))[
                "total"
            ] or Decimal("0")
            damaged = receipts.filter(reason_code="TRANSFER_DAMAGE_RECEIPT").aggregate(
                total=Sum("base_quantity_delta")
            )["total"] or Decimal("0")
            dispatched = -allocation["total"]
            lost = dispatched - accepted - damaged if line.transfer.status == "CLOSED" and line.lost_quantity > 0 else Decimal("0")
            result.append(
                {
                    "batch_id": str(batch_id),
                    "batch_number": allocation["inventory_batch__manufacturer_batch_number"],
                    "dispatched_quantity": str(dispatched),
                    "received_quantity": str(accepted),
                    "damaged_quantity": str(damaged),
                    "lost_quantity": str(lost),
                    "remaining_quantity": str(dispatched - accepted - damaged - lost),
                }
            )
        return result

    class Meta:
        model = StockTransferLine
        fields = [
            "id",
            "sku",
            "sku_code",
            "sku_barcode",
            "sku_name",
            "batch",
            "batch_number",
            "requested_quantity",
            "allocated_quantity",
            "dispatched_quantity",
            "received_quantity",
            "rejected_quantity",
            "damaged_quantity",
            "lost_quantity",
            "unit",
            "discrepancy_reason",
            "dispatch_allocations",
        ]
        read_only_fields = fields


class StockTransferSerializer(serializers.ModelSerializer):
    source_branch_name = serializers.CharField(source="source_branch.name", read_only=True)
    destination_branch_name = serializers.CharField(source="destination_branch.name", read_only=True)
    source_location_name = serializers.CharField(source="source_location.name", read_only=True)
    destination_location_name = serializers.CharField(source="destination_location.name", read_only=True)
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True, allow_null=True)
    approved_by_username = serializers.CharField(source="approved_by.username", read_only=True, allow_null=True)
    dispatched_by_username = serializers.CharField(source="dispatched_by.username", read_only=True, allow_null=True)
    received_by_username = serializers.CharField(source="received_by.username", read_only=True, allow_null=True)
    lines = StockTransferLineSerializer(many=True, read_only=True)

    class Meta:
        model = StockTransfer
        fields = [
            "id",
            "transfer_number",
            "source_branch",
            "source_branch_name",
            "destination_branch",
            "destination_branch_name",
            "source_location",
            "source_location_name",
            "destination_location",
            "destination_location_name",
            "status",
            "requested_by",
            "requested_by_username",
            "approved_by",
            "approved_by_username",
            "dispatched_by",
            "dispatched_by_username",
            "received_by",
            "received_by_username",
            "dispatch_timestamp",
            "receipt_timestamp",
            "reason",
            "document_reference",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class StockTransferRequestLineSerializer(serializers.Serializer):
    sku = serializers.UUIDField()
    quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )


class StockTransferCreateSerializer(serializers.Serializer):
    transfer_number = serializers.CharField(max_length=100)
    source_location = serializers.UUIDField()
    destination_location = serializers.UUIDField()
    reason = serializers.CharField(allow_blank=True, required=False)
    document_reference = serializers.CharField(
        allow_blank=True,
        max_length=255,
        required=False,
    )
    lines = StockTransferRequestLineSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        if attrs["source_location"] == attrs["destination_location"]:
            raise serializers.ValidationError(
                {"destination_location": "Destination must differ from the source location."}
            )
        sku_ids = [line["sku"] for line in attrs["lines"]]
        if len(sku_ids) != len(set(sku_ids)):
            raise serializers.ValidationError({"lines": "Each SKU may appear only once in a transfer request."})
        return attrs


class StockTransferReceiptLineSerializer(serializers.Serializer):
    line_id = serializers.UUIDField()
    batch_id = serializers.UUIDField()
    quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=4,
        min_value=Decimal("0"),
    )
    damaged = serializers.DecimalField(
        max_digits=15,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
    )
    discrepancy_reason = serializers.CharField(allow_blank=True, required=False)

    def validate(self, attrs):
        if attrs["quantity"] + attrs.get("damaged", Decimal("0")) <= 0:
            raise serializers.ValidationError("Record a received or damaged quantity greater than zero.")
        return attrs


class StockTransferReceiveSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=100)
    lines = StockTransferReceiptLineSerializer(many=True, allow_empty=False)

    def validate_lines(self, lines):
        identities = [(line["line_id"], line["batch_id"]) for line in lines]
        if len(identities) != len(set(identities)):
            raise serializers.ValidationError(
                "Each transfer line and batch combination may be received only once per request."
            )
        return lines
