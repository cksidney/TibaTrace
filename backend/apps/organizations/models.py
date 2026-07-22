from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class Organization(TimestampedModel):
    TYPE_PHARMACY = "PHARMACY"
    TYPE_HOSPITAL = "HOSPITAL"
    TYPE_CLINIC = "CLINIC"
    TYPE_CHOICES = (
        (TYPE_PHARMACY, "Pharmacy"),
        (TYPE_HOSPITAL, "Hospital"),
        (TYPE_CLINIC, "Clinic"),
        ("OTHER", "Other"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="healthcare_organizations")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=80)
    organization_type = models.CharField(max_length=40, choices=TYPE_CHOICES, default=TYPE_PHARMACY)
    status = models.CharField(max_length=20, default="ACTIVE")
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_org_tenant_code")]
        indexes = [models.Index(fields=["tenant", "status", "name"], name="ix_org_tenant_status")]


class OrganizationIdentifier(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("organization",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="identifiers")
    system = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "system", "value"], name="uq_org_identifier_tenant")
        ]


class Location(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("organization",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="healthcare_locations")
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="locations")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=80)
    location_type = models.CharField(max_length=50, default="PHARMACY")
    status = models.CharField(max_length=20, default="ACTIVE")
    address = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_location_tenant_code")]
        indexes = [models.Index(fields=["tenant", "organization", "status"], name="ix_location_tenant_org")]


class LocationIdentifier(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("location",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="identifiers")
    system = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "system", "value"], name="uq_location_identifier_tenant")
        ]
