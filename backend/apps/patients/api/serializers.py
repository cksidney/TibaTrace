from rest_framework import serializers

from apps.patients.models import Patient, PatientAllergy, PatientIdentifier, PatientMedication


class PatientIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientIdentifier
        fields = ("id", "system", "value")
        read_only_fields = ("id",)


class PatientAllergySerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientAllergy
        fields = ("id", "allergen_name", "allergen_code", "allergen_system", "reaction", "severity", "notes", "is_active")
        read_only_fields = ("id",)


class PatientMedicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientMedication
        fields = ("id", "medicine", "medication_name", "directions", "status", "effective_start", "effective_end")
        read_only_fields = ("id",)


class PatientSerializer(serializers.ModelSerializer):
    identifiers = PatientIdentifierSerializer(many=True, read_only=True)
    allergies = PatientAllergySerializer(many=True, read_only=True)
    medication_statements = PatientMedicationSerializer(many=True, read_only=True)

    class Meta:
        model = Patient
        fields = (
            "id", "internal_reference_id", "verification_status", "first_name", "last_name",
            "date_of_birth", "sex", "phone", "email", "address", "emergency_contact",
            "is_active", "metadata", "identifiers", "allergies", "medication_statements",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
