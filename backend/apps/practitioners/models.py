from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class Practitioner(TenantConsistencyMixin, TimestampedModel):
    PROFESSION_CHOICES = (
        ("DOCTOR", "Doctor"),
        ("DENTIST", "Dentist"),
        ("CLINICAL_OFFICER", "Clinical officer"),
        ("NURSE_PRESCRIBER", "Nurse prescriber"),
        ("VETERINARY_PRESCRIBER", "Veterinary prescriber"),
        ("OTHER_AUTHORIZED_PRESCRIBER", "Other authorized prescriber"),
    )
    VERIFICATION_CHOICES = (
        ("UNVERIFIED", "Unverified"),
        ("VERIFIED", "Verified"),
        ("REJECTED", "Rejected"),
        ("MANUAL_REVIEW", "Manual review"),
    )
    tenant_relation_fields = ("organization",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="practitioners")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    professional_name = models.CharField(max_length=255, blank=True, default="")
    registration_number = models.CharField(max_length=120, blank=True, default="")
    profession = models.CharField(
        max_length=50,
        choices=PROFESSION_CHOICES,
        default="OTHER_AUTHORIZED_PRESCRIBER",
    )
    licensing_body = models.CharField(max_length=160, blank=True, default="")
    licence_status = models.CharField(max_length=30, default="UNVERIFIED")
    licence_issue_date = models.DateField(null=True, blank=True)
    licence_expiry_date = models.DateField(null=True, blank=True)
    prescribing_scope = models.JSONField(default=list, blank=True)
    controlled_medicine_authority = models.BooleanField(default=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    verification_state = models.CharField(
        max_length=30,
        choices=VERIFICATION_CHOICES,
        default="UNVERIFIED",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default="ACTIVE")
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "registration_number"],
                condition=~Q(registration_number=""),
                name="uq_practitioner_registration",
            )
        ]
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
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    prescribing_scope = models.JSONField(default=list, blank=True)
    controlled_medicine_authority = models.BooleanField(default=False)
    verification_state = models.CharField(max_length=30, default="UNVERIFIED")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "issuer", "licence_number"],
                name="uq_practitioner_licence_tenant",
            )
        ]
