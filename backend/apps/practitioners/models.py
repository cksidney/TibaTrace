from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class Practitioner(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="practitioners")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    status = models.CharField(max_length=20, default="ACTIVE")
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "status", "last_name"], name="ix_practitioner_tenant")]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class PractitionerIdentifier(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("practitioner",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    practitioner = models.ForeignKey(Practitioner, on_delete=models.CASCADE, related_name="identifiers")
    system = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "system", "value"], name="uq_practitioner_identifier_tenant")
        ]


class PractitionerRole(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("practitioner", "organization", "location")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    practitioner = models.ForeignKey(Practitioner, on_delete=models.CASCADE, related_name="roles")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="practitioner_roles")
    location = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, null=True, blank=True)
    role_code = models.CharField(max_length=100)
    specialty_code = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, default="ACTIVE")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "practitioner", "organization", "role_code"],
                name="uq_practitioner_role_scope",
            )
        ]


class PractitionerLicence(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("practitioner",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    practitioner = models.ForeignKey(Practitioner, on_delete=models.CASCADE, related_name="licences")
    licence_number = models.CharField(max_length=100)
    issuer = models.CharField(max_length=100)
    jurisdiction = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, default="VALID")
    expiry_date = models.DateField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "issuer", "licence_number"],
                name="uq_practitioner_licence_tenant",
            )
        ]
