from rest_framework import serializers

from apps.practitioners.models import Practitioner, PractitionerLicence, PractitionerRole


class PractitionerLicenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PractitionerLicence
        fields = (
            "id",
            "licence_number",
            "issuer",
            "jurisdiction",
            "status",
            "issue_date",
            "expiry_date",
            "prescribing_scope",
            "controlled_medicine_authority",
            "verification_state",
            "verified_by",
            "verified_at",
        )
        read_only_fields = ("id", "verified_by", "verified_at")


class PractitionerRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PractitionerRole
        fields = (
            "id",
            "organization",
            "location",
            "role_code",
            "specialty_code",
            "status",
            "start_date",
            "end_date",
        )


class PractitionerSerializer(serializers.ModelSerializer):
    licences = PractitionerLicenceSerializer(many=True, read_only=True)
    roles = PractitionerRoleSerializer(many=True, read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Practitioner
        fields = (
            "id",
            "first_name",
            "last_name",
            "full_name",
            "professional_name",
            "registration_number",
            "profession",
            "licensing_body",
            "licence_status",
            "licence_issue_date",
            "licence_expiry_date",
            "prescribing_scope",
            "controlled_medicine_authority",
            "organization",
            "phone",
            "email",
            "verification_state",
            "verified_by",
            "verified_at",
            "status",
            "metadata",
            "licences",
            "roles",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "licence_status",
            "controlled_medicine_authority",
            "verification_state",
            "verified_by",
            "verified_at",
            "status",
            "metadata",
            "created_at",
            "updated_at",
        )


class PrescriberVerificationSerializer(serializers.Serializer):
    verification_state = serializers.ChoiceField(
        choices=Practitioner.VERIFICATION_CHOICES,
        default="VERIFIED",
    )
    licence_status = serializers.ChoiceField(
        choices=("VALID", "ACTIVE", "EXPIRED", "SUSPENDED", "REVOKED", "UNVERIFIED"),
        required=False,
    )
    verification_note = serializers.CharField(max_length=1000)
    evidence_reference = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["verification_state"] == "VERIFIED" and not attrs.get("evidence_reference", "").strip():
            raise serializers.ValidationError(
                {"evidence_reference": "Verification requires a regulator or licence evidence reference."}
            )
        return attrs


class ControlledAuthorityActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=("GRANT", "REVOKE"))
    reason = serializers.CharField(max_length=1000)
    evidence_reference = serializers.CharField(max_length=255, required=False, allow_blank=True)
