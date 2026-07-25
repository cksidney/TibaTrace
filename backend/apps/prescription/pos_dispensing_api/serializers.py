from rest_framework import serializers

from apps.prescription.models import (
    DispensingEpisode,
    DispensingLine,
    PosDeviceHealthRecord,
    PosShiftRecord,
)

#: Tender types the POS accepts. Kept in step with PaymentTenderType in
#: packages/shared/src/dispensing/types.ts. Only CASH, CARD and MPESA are
#: settled by this release; the remaining values are rejected until their
#: settlement workflow exists, so that a tender cannot be recorded as paid
#: through a path that was never implemented.
TENDER_TYPES = ["CASH", "CARD", "MPESA"]


class PosDispensingLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispensingLine
        fields = [
            "id",
            "prescription_item",
            "prescribed_sku",
            "supplied_sku",
            "inventory_batch",
            "quantity_authorized",
            "quantity_prepared",
            "quantity_supplied",
            "unit",
            "batch_number_snapshot",
            "expiry_date_snapshot",
            "dosage_label_instructions",
            "status",
        ]


class PosDispensingEpisodeSerializer(serializers.ModelSerializer):
    lines = PosDispensingLineSerializer(many=True, read_only=True)

    class Meta:
        model = DispensingEpisode
        fields = [
            "id",
            "dispensing_number",
            "prescription",
            "patient",
            "branch",
            "pharmacy_location",
            "pharmacist",
            "status",
            "initiated_at",
            "completed_at",
            "payment_state",
            "payment_reference",
            "tender_type",
            "paid_amount",
            "collector_name",
            "collector_id_number",
            "collector_phone",
            "collector_relationship",
            "collection_proof_type",
            "collected_at",
            "controlled_witness",
            "controlled_authority_checked",
            "counselling_status",
            "notes",
            "idempotency_key",
            "lines",
        ]
        # Every field that carries clinical, financial or custody meaning is
        # read-only over this surface. These transition only through the gated
        # service actions below (process-payment, confirm-collection, ...), never
        # by direct PATCH -- otherwise the state machine and its clinical gates
        # could be bypassed entirely.
        read_only_fields = [
            "id",
            "dispensing_number",
            "prescription",
            "patient",
            "branch",
            "pharmacy_location",
            "pharmacist",
            "status",
            "initiated_at",
            "completed_at",
            "payment_state",
            "payment_reference",
            "tender_type",
            "paid_amount",
            "collector_name",
            "collector_id_number",
            "collector_phone",
            "collector_relationship",
            "collection_proof_type",
            "collected_at",
            "controlled_witness",
            "controlled_authority_checked",
            "counselling_status",
            "idempotency_key",
        ]


class TransitionStateRequestSerializer(serializers.Serializer):
    new_status = serializers.CharField(max_length=64)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class BatchVerificationRequestSerializer(serializers.Serializer):
    sku_id = serializers.UUIDField()
    batch_number = serializers.CharField(max_length=128)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    quantity_scanned = serializers.DecimalField(max_digits=15, decimal_places=4, default=1)


class ProcessPaymentRequestSerializer(serializers.Serializer):
    tender_type = serializers.ChoiceField(choices=TENDER_TYPES, default="CASH")
    paid_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    payment_reference = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    # Client-generated and stable across retries: this is what makes a replayed
    # payment a no-op instead of a second charge.
    idempotency_key = serializers.CharField(max_length=255)


class PartialDispenseRequestSerializer(serializers.Serializer):
    dispensing_line_id = serializers.UUIDField()
    quantity_supplied = serializers.DecimalField(max_digits=15, decimal_places=4)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=255)


class ControlledVerifyRequestSerializer(serializers.Serializer):
    practitioner_id = serializers.UUIDField()
    collector_id_number = serializers.CharField(max_length=128)
    witness_id = serializers.UUIDField(required=False, allow_null=True)


class CounsellingRecordSerializer(serializers.Serializer):
    medicine_explained = serializers.BooleanField(default=True)
    dosage_explained = serializers.BooleanField(default=True)
    storage_explained = serializers.BooleanField(default=True)
    side_effects_discussed = serializers.BooleanField(default=True)
    interaction_advice_given = serializers.BooleanField(default=True)
    patient_acknowledged = serializers.BooleanField(default=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CollectionConfirmRequestSerializer(serializers.Serializer):
    collector_name = serializers.CharField(max_length=255)
    collector_id_number = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    collector_phone = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    collector_relationship = serializers.CharField(max_length=128, required=False, allow_blank=True, default="SELF")
    collection_proof_type = serializers.CharField(max_length=64, required=False, allow_blank=True, default="SIGNATURE")
    signature_ref = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=255)


class ShiftStartSerializer(serializers.Serializer):
    shift_number = serializers.CharField(max_length=64)
    controlled_start_count = serializers.IntegerField(default=0)
    location_id = serializers.UUIDField(required=False, allow_null=True)


class ShiftEndSerializer(serializers.Serializer):
    controlled_end_count = serializers.IntegerField(default=0)
    declaration_notes = serializers.CharField(required=False, allow_blank=True, default="")


class PosShiftRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = PosShiftRecord
        fields = [
            "id",
            "shift_number",
            "cashier",
            "pharmacist",
            "location",
            "started_at",
            "ended_at",
            "status",
            "controlled_stock_start_count",
            "controlled_stock_end_count",
            "outstanding_episode_count",
            "discrepancy_declared",
            "declaration_notes",
        ]
        read_only_fields = fields


class DeviceTelemetrySerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    device_type = serializers.CharField(max_length=64, default="TERMINAL")
    status = serializers.CharField(max_length=32, default="OK")
    printer_paper_level = serializers.CharField(max_length=32, default="OK")
    scanner_connected = serializers.BooleanField(default=True)
    cash_drawer_open = serializers.BooleanField(default=False)
    network_latency_ms = serializers.IntegerField(default=0)
    battery_level_pct = serializers.IntegerField(required=False, allow_null=True)
    storage_used_pct = serializers.IntegerField(default=0)


class PosDeviceHealthRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = PosDeviceHealthRecord
        fields = [
            "id",
            "device_id",
            "device_type",
            "status",
            "printer_paper_level",
            "scanner_connected",
            "cash_drawer_open",
            "network_latency_ms",
            "battery_level_pct",
            "storage_used_pct",
            "last_heartbeat",
        ]
