from rest_framework import serializers

from apps.patients.models import (
    Patient,
    PatientAllergy,
    PatientClinicalSummary,
    PatientConditionSummary,
    PatientIdentifier,
    PatientMedication,
)
from apps.prescription.models import PatientMedicationHistory


class PatientIdentifierSerializer(serializers.ModelSerializer):
    masked_value = serializers.CharField(read_only=True)

    class Meta:
        model = PatientIdentifier
        fields = (
            "id",
            "identifier_type",
            "system",
            "masked_value",
            "verification_status",
            "issuing_authority",
            "issue_date",
            "expiry_date",
        )
        read_only_fields = fields


class PatientIdentifierCreateSerializer(serializers.Serializer):
    identifier_type = serializers.ChoiceField(
        choices=PatientIdentifier.IDENTIFIER_TYPES
    )
    value = serializers.CharField(write_only=True)
    system = serializers.CharField(required=False, allow_blank=True)
    verification_status = serializers.ChoiceField(
        choices=PatientIdentifier.VERIFICATION_STATUSES,
        default="UNVERIFIED",
    )
    issuing_authority = serializers.CharField(required=False, allow_blank=True)
    issue_date = serializers.DateField(required=False, allow_null=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)


class PatientAllergySerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientAllergy
        fields = (
            "id",
            "allergen_name",
            "allergen_code",
            "allergen_system",
            "medicinal_product",
            "active_ingredient",
            "reaction",
            "severity",
            "onset_date",
            "verification_status",
            "source",
            "recorded_by",
            "reviewed_by",
            "status",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "recorded_by", "created_at", "updated_at")


class PatientMedicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientMedication
        fields = (
            "id",
            "medicine",
            "medication_name",
            "directions",
            "status",
            "effective_start",
            "effective_end",
        )
        read_only_fields = ("id",)


class PatientClinicalSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientClinicalSummary
        fields = (
            "id",
            "pregnancy_status",
            "lactation_status",
            "renal_impairment",
            "hepatic_impairment",
            "height_cm",
            "weight_kg",
            "source",
            "verification_status",
            "verified_by",
            "verified_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "verified_by",
            "verified_at",
            "created_at",
            "updated_at",
        )


class PatientConditionSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientConditionSummary
        fields = (
            "id",
            "code",
            "code_system",
            "description",
            "status",
            "onset_date",
            "source",
            "verification_status",
            "recorded_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "recorded_by", "created_at", "updated_at")


class PatientMedicationHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientMedicationHistory
        fields = (
            "id",
            "prescription",
            "prescription_item",
            "dispensing_episode",
            "medicine_name_snapshot",
            "supplied_sku",
            "active_ingredient_snapshot",
            "strength_snapshot",
            "dosage_form_snapshot",
            "inventory_batch",
            "quantity",
            "instructions",
            "supplied_at",
            "intended_start_date",
            "intended_end_date",
            "status",
            "source",
            "reversal_reference",
        )
        read_only_fields = fields


class PatientSerializer(serializers.ModelSerializer):
    identifiers = PatientIdentifierSerializer(many=True, read_only=True)
    allergies = PatientAllergySerializer(many=True, read_only=True)
    medication_statements = PatientMedicationSerializer(many=True, read_only=True)
    clinical_summary = PatientClinicalSummarySerializer(read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Patient
        fields = (
            "id",
            "internal_reference_id",
            "patient_number",
            "external_patient_reference",
            "verification_status",
            "first_name",
            "last_name",
            "full_name",
            "preferred_name",
            "date_of_birth",
            "sex",
            "phone",
            "email",
            "address",
            "emergency_contact",
            "preferred_language",
            "communication_preference",
            "guardian_or_caregiver",
            "is_deceased",
            "consent_status",
            "record_restrictions",
            "is_active",
            "metadata",
            "identifiers",
            "allergies",
            "medication_statements",
            "clinical_summary",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def _privacy_capabilities(self):
        request = self.context.get("request")
        view = self.context.get("view")
        if not request or getattr(view, "swagger_fake_view", False):
            return {"*"}
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return set()
        capabilities = getattr(request, "effective_capabilities", None)
        if capabilities is None:
            capabilities = user.effective_capabilities(
                tenant_id=getattr(request, "tenant_id", None),
            )
            request.effective_capabilities = capabilities
        return capabilities

    def get_fields(self):
        fields = super().get_fields()
        capabilities = self._privacy_capabilities()
        can_view_sensitive = (
            "*" in capabilities or "patients.sensitive.view" in capabilities
        )
        can_view_identity = (
            "*" in capabilities or "patients.identity.view" in capabilities
        )
        if not can_view_sensitive:
            for field_name in (
                "allergies",
                "medication_statements",
                "clinical_summary",
            ):
                fields.pop(field_name, None)
        if not can_view_identity:
            fields.pop("identifiers", None)
        return fields

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        request = self.context.get("request")
        if not request:
            return representation
        capabilities = self._privacy_capabilities()
        can_view_sensitive = (
            "*" in capabilities or "patients.sensitive.view" in capabilities
        )
        can_view_identity = (
            "*" in capabilities or "patients.identity.view" in capabilities
        )
        if not can_view_sensitive:
            for field in (
                "phone",
                "email",
                "address",
                "emergency_contact",
                "guardian_or_caregiver",
                "record_restrictions",
                "metadata",
            ):
                representation[field] = None
            representation["allergies"] = []
            representation["medication_statements"] = []
            representation["clinical_summary"] = None
        if not can_view_identity:
            representation["identifiers"] = []
            representation["external_patient_reference"] = ""
        return representation
