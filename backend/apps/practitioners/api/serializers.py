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
            "verification_state",
            "verified_by",
            "verified_at",
            "created_at",
            "updated_at",
        )


class PrescriberVerificationSerializer(serializers.Serializer):
    verification_state = serializers.ChoiceField(
        choices=Practitioner.VERIFICATION_CHOICES,
        default="VERIFIED",
    )
    licence_status = serializers.CharField(required=False)
    controlled_medicine_authority = serializers.BooleanField(required=False)
