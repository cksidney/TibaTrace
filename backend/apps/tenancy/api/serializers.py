from rest_framework import serializers

from apps.identity.models import User
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient
from apps.practitioners.models import Practitioner
from apps.tenancy.models import Tenant


class TenantSerializer(serializers.ModelSerializer):
    active_location_count = serializers.SerializerMethodField()
    active_organization_count = serializers.SerializerMethodField()
    active_patient_count = serializers.SerializerMethodField()
    active_practitioner_count = serializers.SerializerMethodField()
    active_user_count = serializers.SerializerMethodField()
    suspension_reason = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "status",
            "country_code",
            "time_zone",
            "metadata",
            "suspension_reason",
            "active_location_count",
            "active_organization_count",
            "active_patient_count",
            "active_practitioner_count",
            "active_user_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "suspension_reason",
            "active_location_count",
            "active_organization_count",
            "active_patient_count",
            "active_practitioner_count",
            "active_user_count",
            "created_at",
            "updated_at",
        ]

    def get_active_location_count(self, tenant):
        return Location.all_objects.filter(tenant=tenant, status="ACTIVE").count()

    def get_active_organization_count(self, tenant):
        return Organization.all_objects.filter(tenant=tenant, status="ACTIVE").count()

    def get_active_patient_count(self, tenant):
        return Patient.all_objects.filter(tenant=tenant, is_active=True).count()

    def get_active_practitioner_count(self, tenant):
        return Practitioner.all_objects.filter(tenant=tenant, status="ACTIVE").count()

    def get_active_user_count(self, tenant):
        return User.objects.filter(tenant=tenant, is_active=True).count()

    def get_suspension_reason(self, tenant):
        return str((tenant.metadata or {}).get("suspension_reason", ""))


class TenantSuspensionSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)
