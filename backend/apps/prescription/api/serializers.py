from rest_framework import serializers

from apps.prescription.models import Prescription, PrescriptionDispense, PrescriptionFill, PrescriptionItem


class PrescriptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionItem
        fields = (
            "id", "canonical_medicine", "medication_name", "dosage_instruction", "dose_amount", "dose_unit",
            "frequency_per_day", "duration_days", "quantity", "refills_authorized", "is_controlled", "route",
        )
        read_only_fields = ("id",)


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        fields = (
            "id", "patient", "practitioner", "organization", "location", "prescription_number", "status",
            "workflow_state", "issued_at", "expires_at", "substitution_policy", "clinical_review_id",
            "approved_at", "approved_by", "payment_reference", "metadata", "items", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "status", "workflow_state", "clinical_review_id", "approved_at", "approved_by",
            "payment_reference", "created_at", "updated_at",
        )

    def validate(self, attrs):
        tenant_id = str(self.context["request"].tenant_id)
        for field in ("patient", "practitioner", "organization", "location"):
            related = attrs.get(field) or getattr(self.instance, field, None)
            if related and str(related.tenant_id) != tenant_id:
                raise serializers.ValidationError({field: "Related record is outside the active tenant."})
        return attrs


class PrescriptionFillSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionFill
        fields = ("id", "item", "quantity_dispensed", "substituted_medicine")


class PrescriptionDispenseSerializer(serializers.ModelSerializer):
    fills = PrescriptionFillSerializer(many=True, read_only=True)

    class Meta:
        model = PrescriptionDispense
        fields = ("id", "prescription", "location", "dispensed_at", "status", "dispensed_by", "idempotency_key", "fills")
