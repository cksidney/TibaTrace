from rest_framework import serializers

from apps.prescription.models import (
    DispensingEpisode,
    DispensingLine,
    PosDeviceHealthRecord,
    PosShiftRecord,
)
from apps.prescription.pos_printing_models import PosPrintJob

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

    # Money owed and money taken come from the latest PaymentIntent, which is
    # the authoritative ledger. It must remain visible after settlement too:
    # querying only active intents made a confirmed payment look unpriced on
    # the next native-client refresh. The episode's own paid_amount is a
    # convenience mirror and must never be presented as the amount due.
    amount_due = serializers.SerializerMethodField()
    amount_settled = serializers.SerializerMethodField()
    amount_remaining = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()

    def _intent(self, episode):
        from apps.prescription.payment_models import PaymentIntent

        cached = getattr(episode, "_payment_intent", None)
        if cached is None:
            cached = (
                PaymentIntent.all_objects.filter(dispensing_episode=episode)
                .order_by("-created_at")
                .first()
            )
            # Cache the miss too, so a null result does not re-query per field.
            episode._payment_intent = cached or False
        return cached or None

    def get_amount_due(self, episode):
        intent = self._intent(episode)
        return str(intent.amount_due) if intent else None

    def get_amount_settled(self, episode):
        intent = self._intent(episode)
        return str(intent.effective_settled) if intent else None

    def get_amount_remaining(self, episode):
        intent = self._intent(episode)
        return str(intent.amount_remaining) if intent else None

    def get_currency(self, episode):
        intent = self._intent(episode)
        return intent.currency if intent else None

    # ── who is actually at the counter ───────────────────────────────────────
    #
    # This surface previously sent `patient` and `prescription` as bare ids and
    # nothing else, so the till had no name, number, date of birth, prescriber
    # or cover to display. The POS filled every one of those from a hardcoded
    # demo patient, which meant it showed the same fictional person for every
    # episode. An operator dispensing against a displayed identity that is never
    # the patient's is the failure this exists to prevent, so the real values
    # are sent here and the client renders absence as absence.
    #
    # Every one of these is None when the underlying record is missing. None is
    # a truthful answer; a placeholder is not.
    patient_name = serializers.SerializerMethodField()
    patient_number = serializers.SerializerMethodField()
    patient_sex = serializers.SerializerMethodField()
    patient_date_of_birth = serializers.SerializerMethodField()
    prescription_number = serializers.SerializerMethodField()
    prescriber_name = serializers.SerializerMethodField()
    insurer_name = serializers.SerializerMethodField()
    scheme_name = serializers.SerializerMethodField()
    membership_number = serializers.SerializerMethodField()
    allergies = serializers.SerializerMethodField()

    def get_patient_name(self, episode):
        patient = episode.patient
        if not patient:
            return None
        parts = [patient.first_name, patient.last_name]
        return " ".join(p for p in parts if p).strip() or None

    def get_patient_number(self, episode):
        return getattr(episode.patient, "patient_number", None) or None

    def get_patient_sex(self, episode):
        return getattr(episode.patient, "sex", None) or None

    def get_patient_date_of_birth(self, episode):
        dob = getattr(episode.patient, "date_of_birth", None)
        return dob.isoformat() if dob else None

    def get_prescription_number(self, episode):
        return getattr(episode.prescription, "prescription_number", None) or None

    def get_prescriber_name(self, episode):
        practitioner = getattr(episode.prescription, "practitioner", None)
        if not practitioner:
            return None
        professional = (practitioner.professional_name or "").strip()
        if professional:
            return professional
        parts = [practitioner.first_name, practitioner.last_name]
        return " ".join(p for p in parts if p).strip() or None

    def _coverage(self, episode):
        """The patient's active cover, or None.

        Only ACTIVE cover that is current on today's date counts. Expired cover
        shown as though it were live tells a cashier to bill an insurer that
        will refuse the claim.
        """
        from django.db.models import Q
        from django.utils import timezone

        from apps.insurance.models import InsuranceCoverage

        cached = getattr(episode, "_coverage_cache", None)
        if cached is None:
            today = timezone.localdate()
            cached = (
                InsuranceCoverage.all_objects.filter(
                    tenant_id=episode.tenant_id,
                    patient_id=episode.patient_id,
                    status=InsuranceCoverage.Status.ACTIVE,
                )
                .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
                .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
                .select_related("member", "scheme", "scheme__insurer")
                .order_by("-valid_from")
                .first()
            )
            episode._coverage_cache = cached or False
        return cached or None

    def get_insurer_name(self, episode):
        coverage = self._coverage(episode)
        insurer = getattr(getattr(coverage, "scheme", None), "insurer", None)
        return getattr(insurer, "name", None) or None

    def get_scheme_name(self, episode):
        coverage = self._coverage(episode)
        return getattr(getattr(coverage, "scheme", None), "name", None) or None

    def get_membership_number(self, episode):
        coverage = self._coverage(episode)
        return getattr(getattr(coverage, "member", None), "membership_number", None) or None

    def get_allergies(self, episode):
        """Recorded allergies, or an empty list.

        An empty list means "none recorded", which is not the same as "none" --
        the client must say which. What it must never do is state a specific
        allergy that was never recorded, which is what the hardcoded
        "Penicillin Conflict Reported" tag did on every episode.
        """
        from apps.patients.models import PatientAllergy

        if not episode.patient_id:
            return []
        # REFUTED is a `status` value; `verification_status` carries
        # UNVERIFIED / PATIENT_REPORTED / CLINICIAN_VERIFIED. Excluding the
        # wrong field would keep showing an allergy a clinician has ruled out.
        rows = PatientAllergy.all_objects.filter(
            tenant_id=episode.tenant_id, patient_id=episode.patient_id, is_active=True
        ).exclude(status="REFUTED")
        return [
            {
                "allergen_name": row.allergen_name,
                "severity": row.severity or None,
                "reaction": row.reaction or None,
                "verification_status": row.verification_status or None,
            }
            for row in rows
        ]

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
            "payment_register_session",
            "payment_operator_shift",
            "payment_device_id",
            "amount_due",
            "amount_settled",
            "amount_remaining",
            "currency",
            "patient_name",
            "patient_number",
            "patient_sex",
            "patient_date_of_birth",
            "prescription_number",
            "prescriber_name",
            "insurer_name",
            "scheme_name",
            "membership_number",
            "allergies",
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
            "payment_register_session",
            "payment_operator_shift",
            "payment_device_id",
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
    device_id = serializers.CharField(max_length=128)
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


class PosPrintJobSerializer(serializers.ModelSerializer):
    document_number = serializers.CharField(source="document.document_number", read_only=True)
    document_type = serializers.CharField(source="document.document_type", read_only=True)

    class Meta:
        model = PosPrintJob
        fields = [
            "id",
            "document",
            "document_number",
            "document_type",
            "branch",
            "device_id",
            "printer",
            "transport",
            "status",
            "copy_classification",
            "copy_number",
            "reprint_reason",
            "requested_by",
            "requested_at",
            "attempt_count",
            "last_attempt_at",
            "failure_code",
            "failure_message",
            "printed_at",
            "printed_by",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrintResultSerializer(serializers.Serializer):
    succeeded = serializers.BooleanField()
    failure_code = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    failure_message = serializers.CharField(required=False, allow_blank=True, default="")
    retryable = serializers.BooleanField(required=False, default=True)


class PrintCancellationSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True)


class PrintReprintSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True)
    printer = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    transport = serializers.ChoiceField(
        choices=PosPrintJob.Transport.choices,
        required=False,
        default=PosPrintJob.Transport.SIMULATOR,
    )
