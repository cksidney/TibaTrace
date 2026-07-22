from rest_framework import serializers

from apps.organizations.models import Location, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name", "code", "organization_type", "status", "metadata", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ("id", "organization", "name", "code", "location_type", "status", "address", "metadata", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_organization(self, value):
        if str(value.tenant_id) != str(self.context["request"].tenant_id):
            raise serializers.ValidationError("Organization is outside the active tenant.")
        return value
