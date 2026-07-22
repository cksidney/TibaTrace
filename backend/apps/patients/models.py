from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class Patient(TimestampedModel):
    SEX_CHOICES = (("MALE", "Male"), ("FEMALE", "Female"), ("OTHER", "Other"), ("UNKNOWN", "Unknown"))

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="patients")
    internal_reference_id = models.CharField(max_length=255)
    verification_status = models.CharField(max_length=50, default="UNVERIFIED")
    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=16, choices=SEX_CHOICES, default="UNKNOWN")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.JSONField(default=dict, blank=True)
    emergency_contact = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "internal_reference_id"], name="uq_patient_reference_tenant")
        ]
        indexes = [
            models.Index(fields=["tenant", "verification_status"], name="ix_patient_verify_tenant"),
            models.Index(fields=["tenant", "last_name", "first_name"], name="ix_patient_name_tenant"),
        ]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class PatientIdentifier(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("patient",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="identifiers")
    system = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "system", "value"], name="uq_patient_identifier_tenant")
        ]


class PatientAllergy(TenantConsistencyMixin, TimestampedModel):
    SEVERITY_INFO = "INFO"
    SEVERITY_WARNING = "WARNING"
    SEVERITY_HARD_STOP = "HARD_STOP"
    SEVERITY_CHOICES = (
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_HARD_STOP, "Hard stop"),
    )
    tenant_relation_fields = ("patient",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="allergies")
    allergen_name = models.CharField(max_length=160)
    allergen_code = models.CharField(max_length=100, blank=True)
    allergen_system = models.CharField(max_length=255, blank=True)
    reaction = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_WARNING)
    notes = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "patient", "is_active"], name="ix_patient_allergy_active"),
            models.Index(fields=["tenant", "allergen_name"], name="ix_patient_allergen"),
        ]


class PatientMedication(TenantConsistencyMixin, TimestampedModel):
    STATUS_CHOICES = (("ACTIVE", "Active"), ("COMPLETED", "Completed"), ("STOPPED", "Stopped"))
    tenant_relation_fields = ("patient",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="medication_statements")
    medicine = models.ForeignKey("medicines.Medicine", on_delete=models.PROTECT, null=True, blank=True)
    medication_name = models.CharField(max_length=255)
    directions = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="ACTIVE")
    effective_start = models.DateTimeField(null=True, blank=True)
    effective_end = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()
