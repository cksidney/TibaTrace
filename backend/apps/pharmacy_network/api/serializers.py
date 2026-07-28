from __future__ import annotations

from rest_framework import serializers

from apps.pharmacy_network.models import PharmacyProfile, TenantLifecycleEvent
from apps.tenancy.models import Tenant


class PharmacyProfileSerializer(serializers.ModelSerializer):
    #: Derived, not stored: whether the premises may legally dispense today.
    licence_is_current = serializers.BooleanField(read_only=True)
    days_until_licence_expiry = serializers.IntegerField(read_only=True)

    class Meta:
        model = PharmacyProfile
        fields = (
            "legal_name",
            "business_registration_number",
            "kra_pin",
            "ppb_premises_licence_number",
            "ppb_licence_expiry",
            "superintendent_name",
            "superintendent_ppb_number",
            "primary_contact_name",
            "primary_contact_email",
            "primary_contact_phone",
            "onboarding_started_at",
            "activated_at",
            "terminated_at",
            "notes",
            "licence_is_current",
            "days_until_licence_expiry",
        )
        read_only_fields = ("onboarding_started_at", "activated_at", "terminated_at")


class PharmacySerializer(serializers.ModelSerializer):
    profile = PharmacyProfileSerializer(source="pharmacy_profile", read_only=True)
    #: What this pharmacy may legitimately do next. The client renders exactly
    #: these, so a button never offers a transition the service will refuse.
    available_transitions = serializers.SerializerMethodField()
    branch_count = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = (
            "id",
            "name",
            "slug",
            "status",
            "country_code",
            "time_zone",
            "created_at",
            "profile",
            "available_transitions",
            "branch_count",
        )
        read_only_fields = fields

    def get_available_transitions(self, tenant) -> list[str]:
        from apps.pharmacy_network.services import ALLOWED_TRANSITIONS

        return sorted(ALLOWED_TRANSITIONS.get(tenant.status, frozenset()))

    def get_branch_count(self, tenant) -> int:
        from apps.organizations.models import Location

        return Location.all_objects.filter(tenant_id=tenant.pk).count()


class TenantLifecycleEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = TenantLifecycleEvent
        fields = (
            "id",
            "from_state",
            "to_state",
            "actor_name",
            "reason",
            "occurred_at",
            "context",
        )

    def get_actor_name(self, event) -> str | None:
        # None means the platform did it, not that nobody is accountable.
        return event.actor.username if event.actor else None


class RegisterPharmacySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    slug = serializers.SlugField(max_length=120)
    legal_name = serializers.CharField(max_length=200)
    country_code = serializers.CharField(max_length=2, required=False, default="KE")
    time_zone = serializers.CharField(max_length=64, required=False, default="Africa/Nairobi")
    business_registration_number = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    kra_pin = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    ppb_premises_licence_number = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    ppb_licence_expiry = serializers.DateField(required=False, allow_null=True, default=None)
    superintendent_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    superintendent_ppb_number = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    primary_contact_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    primary_contact_email = serializers.EmailField(required=False, allow_blank=True, default="")
    primary_contact_phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")


class BeginOnboardingSerializer(serializers.Serializer):
    organization_name = serializers.CharField(max_length=200)
    organization_code = serializers.CharField(max_length=40)
    branch_name = serializers.CharField(max_length=200)
    branch_code = serializers.CharField(max_length=40)


class ReasonSerializer(serializers.Serializer):
    """A stated reason. Required where the transition stops a pharmacy trading."""

    reason = serializers.CharField(allow_blank=False)


class OptionalReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
