from rest_framework import serializers

from apps.practitioners.models import Practitioner, PractitionerLicence, PractitionerRole


class PractitionerLicenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PractitionerLicence
        fields = ("id", "licence_number", "issuer", "jurisdiction", "status", "expiry_date")


class PractitionerRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PractitionerRole
        fields = ("id", "organization", "location", "role_code", "specialty_code", "status", "start_date", "end_date")


class PractitionerSerializer(serializers.ModelSerializer):
    licences = PractitionerLicenceSerializer(many=True, read_only=True)
    roles = PractitionerRoleSerializer(many=True, read_only=True)

    class Meta:
        model = Practitioner
        fields = ("id", "first_name", "last_name", "phone", "email", "status", "metadata", "licences", "roles", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")
