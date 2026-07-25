from rest_framework import serializers

from apps.cds.models import ClinicalFinding
from apps.prescription.models import (
    ClinicalSubstitution,
    ClinicalWorkItem,
    DispensingAllocation,
    DispensingCheck,
    DispensingEpisode,
    DispensingLabel,
    DispensingLine,
    DispensingReservation,
    DispensingReversal,
    MedicineSupply,
    MedicineSupplyLine,
    PatientCounselling,
    PatientReturn,
    PatientReturnLine,
    PharmacistClinicalReview,
    PharmacistIntervention,
    PharmacistVerification,
    Prescription,
    PrescriptionDispense,
    PrescriptionFill,
    PrescriptionItem,
    PrescriptionValidationFinding,
)


class ReadOnlyModelSerializer(serializers.ModelSerializer):
    def get_fields(self):
        fields = super().get_fields()
        for field in fields.values():
            field.read_only = True
        return fields


class PrescriptionItemSerializer(serializers.ModelSerializer):
    total_authorized_quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=4,
        read_only=True,
    )

    class Meta:
        model = PrescriptionItem
        fields = (
            "id",
            "canonical_medicine",
            "prescribed_medicinal_product",
            "prescribed_brand",
            "prescribed_sku",
            "medication_name",
            "prescribed_description_snapshot",
            "active_ingredient_snapshot",
            "strength_snapshot",
            "dosage_form_snapshot",
            "dosage_instruction",
            "dose_amount",
            "dose_unit",
            "frequency_per_day",
            "duration_days",
            "quantity",
            "unit",
            "refills_authorized",
            "repeats_remaining",
            "quantity_supplied_total",
            "total_authorized_quantity",
            "minimum_repeat_interval_days",
            "earliest_refill_date",
            "latest_refill_date",
            "is_controlled",
            "route",
            "indication",
            "special_instructions",
            "maximum_daily_dose",
            "start_date",
            "end_date",
            "substitution_policy",
            "status",
            "clinical_notes",
        )
        read_only_fields = (
            "id",
            "prescribed_description_snapshot",
            "active_ingredient_snapshot",
            "strength_snapshot",
            "dosage_form_snapshot",
            "repeats_remaining",
            "quantity_supplied_total",
            "total_authorized_quantity",
        )


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        fields = (
            "id",
            "patient",
            "practitioner",
            "organization",
            "location",
            "prescribing_organization",
            "prescription_number",
            "external_prescription_reference",
            "prescription_date",
            "received_at",
            "prescription_type",
            "source_channel",
            "original_document",
            "status",
            "workflow_state",
            "issued_at",
            "expires_at",
            "substitution_policy",
            "is_controlled_medicine",
            "repeat_authorization",
            "repeats_allowed",
            "repeats_remaining",
            "legal_validation_state",
            "clinical_review_state",
            "pharmacist_verification_state",
            "dispensing_state",
            "clinical_review_id",
            "approved_at",
            "approved_by",
            "payment_reference",
            "notes",
            "metadata",
            "items",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "received_at",
            "status",
            "workflow_state",
            "legal_validation_state",
            "clinical_review_state",
            "pharmacist_verification_state",
            "dispensing_state",
            "clinical_review_id",
            "approved_at",
            "approved_by",
            "payment_reference",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        tenant_id = str(self.context["request"].tenant_id)
        for field in (
            "patient",
            "practitioner",
            "organization",
            "location",
            "prescribing_organization",
            "original_document",
        ):
            related = attrs.get(field) or getattr(self.instance, field, None)
            if related and str(related.tenant_id) != tenant_id:
                raise serializers.ValidationError(
                    {field: "Related record is outside the active tenant."}
                )
        return attrs


class PrescriptionValidationFindingSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = PrescriptionValidationFinding
        fields = "__all__"


class ClinicalFindingSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = ClinicalFinding
        fields = (
            "id",
            "evaluation",
            "prescription",
            "prescription_item",
            "affected_medicine",
            "rule_id",
            "rule_version",
            "rule_type",
            "clinical_category",
            "source",
            "source_version",
            "effective_date",
            "severity",
            "evidence_summary",
            "explanation",
            "recommended_action",
            "override_policy",
            "interacting_factor",
            "resolution_status",
            "resolved_by",
            "resolution_reason",
            "resolved_at",
            "created_at",
        )
        read_only_fields = fields


class PharmacistClinicalReviewSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = PharmacistClinicalReview
        fields = "__all__"


class PharmacistInterventionSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = PharmacistIntervention
        fields = "__all__"


class PharmacistVerificationSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = PharmacistVerification
        fields = "__all__"


class ClinicalSubstitutionSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = ClinicalSubstitution
        fields = "__all__"


class ClinicalWorkItemSerializer(ReadOnlyModelSerializer):
    prescription_number = serializers.CharField(
        source="prescription.prescription_number",
        read_only=True,
    )
    dispensing_number = serializers.CharField(
        source="dispensing_episode.dispensing_number",
        read_only=True,
        allow_null=True,
    )
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = ClinicalWorkItem
        fields = (
            "id",
            "queue_type",
            "prescription",
            "prescription_number",
            "dispensing_episode",
            "dispensing_number",
            "branch",
            "branch_name",
            "required_capability",
            "status",
            "due_at",
            "closed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class DispensingReservationSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = DispensingReservation
        fields = "__all__"


class DispensingAllocationSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = DispensingAllocation
        fields = "__all__"


class DispensingLineSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = DispensingLine
        fields = "__all__"


class DispensingCheckSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = DispensingCheck
        fields = "__all__"


class DispensingLabelSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = DispensingLabel
        fields = "__all__"


class PatientCounsellingSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = PatientCounselling
        fields = "__all__"


class MedicineSupplyLineSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = MedicineSupplyLine
        fields = "__all__"


class MedicineSupplySerializer(serializers.ModelSerializer):
    lines = MedicineSupplyLineSerializer(many=True, read_only=True)

    class Meta:
        model = MedicineSupply
        fields = (
            "id",
            "supply_number",
            "episode",
            "prescription",
            "patient",
            "supplied_by",
            "supplied_at",
            "status",
            "idempotency_key",
            "correlation_id",
            "lines",
        )
        read_only_fields = fields


class DispensingReversalSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = DispensingReversal
        fields = "__all__"


class DispensingEpisodeSerializer(serializers.ModelSerializer):
    lines = DispensingLineSerializer(many=True, read_only=True)
    reservations = DispensingReservationSerializer(many=True, read_only=True)
    allocations = DispensingAllocationSerializer(many=True, read_only=True)
    supplies = MedicineSupplySerializer(many=True, read_only=True)

    class Meta:
        model = DispensingEpisode
        fields = (
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
            "supply_method",
            "sales_order",
            "payment_state",
            "counselling_status",
            "notes",
            "idempotency_key",
            "lines",
            "reservations",
            "allocations",
            "supplies",
        )
        read_only_fields = fields


class PatientReturnLineSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = PatientReturnLine
        fields = "__all__"


class PatientReturnSerializer(ReadOnlyModelSerializer):
    lines = PatientReturnLineSerializer(many=True, read_only=True)

    class Meta:
        model = PatientReturn
        fields = "__all__"


class PrescriptionFillSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionFill
        fields = ("id", "item", "quantity_dispensed", "substituted_medicine")


class PrescriptionDispenseSerializer(serializers.ModelSerializer):
    fills = PrescriptionFillSerializer(many=True, read_only=True)

    class Meta:
        model = PrescriptionDispense
        fields = (
            "id",
            "prescription",
            "location",
            "dispensed_at",
            "status",
            "dispensed_by",
            "idempotency_key",
            "fills",
        )


class DispensingEpisodeCreateSerializer(serializers.Serializer):
    prescription_id = serializers.UUIDField()
    branch_id = serializers.UUIDField()
    pharmacy_location_id = serializers.UUIDField()
    supply_method = serializers.CharField(default="PATIENT_COLLECTION")
    sales_order_id = serializers.UUIDField(required=False, allow_null=True)
    # Only non-settlement states may be requested at creation: an episode
    # must never be created already PAID.
    payment_state = serializers.ChoiceField(
        choices=sorted(DispensingEpisode.PAYMENT_STATES_AT_CREATION),
        required=False,
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(required=False)


class DispensingReserveSerializer(serializers.Serializer):
    prescription_item_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=4)
    minimum_shelf_life_days = serializers.IntegerField(default=0, min_value=0)
    substitute_sku_id = serializers.UUIDField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(required=False)


class DispensingSupplySerializer(serializers.Serializer):
    line_quantities = serializers.DictField(
        child=serializers.DecimalField(max_digits=15, decimal_places=4),
        required=False,
    )
    partial_reason = serializers.CharField(required=False, allow_blank=True)
    next_eligible_date = serializers.DateField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(required=False)


class PatientReturnReceiveSerializer(serializers.Serializer):
    supply_id = serializers.UUIDField()
    quarantine_location_id = serializers.UUIDField()
    reason = serializers.CharField()
    lines = serializers.ListField(child=serializers.DictField())
    idempotency_key = serializers.CharField(required=False)
