from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class Patient(TenantConsistencyMixin, TimestampedModel):
    SEX_CHOICES = (("MALE", "Male"), ("FEMALE", "Female"), ("OTHER", "Other"), ("UNKNOWN", "Unknown"))

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="patients")
    internal_reference_id = models.CharField(max_length=255)
    patient_number = models.CharField(max_length=80, blank=True, default="")
    external_patient_reference = models.CharField(max_length=160, blank=True, default="")
    verification_status = models.CharField(max_length=50, default="UNVERIFIED")
    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    preferred_name = models.CharField(max_length=160, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=16, choices=SEX_CHOICES, default="UNKNOWN")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.JSONField(default=dict, blank=True)
    emergency_contact = models.JSONField(default=dict, blank=True)
    preferred_language = models.CharField(max_length=40, blank=True, default="")
    communication_preference = models.CharField(max_length=40, blank=True, default="")
    guardian_or_caregiver = models.JSONField(default=dict, blank=True)
    is_deceased = models.BooleanField(default=False)
    consent_status = models.CharField(max_length=40, default="NOT_RECORDED")
    record_restrictions = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "internal_reference_id"], name="uq_patient_reference_tenant"),
            models.UniqueConstraint(
                fields=["tenant", "patient_number"],
                condition=~Q(patient_number=""),
                name="uq_patient_number_tenant",
            ),
            models.UniqueConstraint(
                fields=["tenant", "external_patient_reference"],
                condition=~Q(external_patient_reference=""),
                name="uq_patient_external_ref_tenant",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "verification_status"], name="ix_patient_verify_tenant"),
            models.Index(fields=["tenant", "last_name", "first_name"], name="ix_patient_name_tenant"),
        ]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class PatientIdentifier(TenantConsistencyMixin, TimestampedModel):
    IDENTIFIER_TYPES = (
        ("NATIONAL_ID", "National ID"),
        ("PASSPORT", "Passport"),
        ("BIRTH_CERTIFICATE", "Birth certificate"),
        ("HOSPITAL_NUMBER", "Hospital number"),
        ("INSURANCE_NUMBER", "Insurance number"),
        ("REFUGEE_ID", "Refugee ID"),
        ("OTHER", "Other"),
    )
    VERIFICATION_STATUSES = (
        ("UNVERIFIED", "Unverified"),
        ("VERIFIED", "Verified"),
        ("REJECTED", "Rejected"),
        ("EXPIRED", "Expired"),
    )

    tenant_relation_fields = ("patient",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="identifiers")
    system = models.CharField(max_length=255)
    value = models.CharField(max_length=255, blank=True, default="")
    identifier_type = models.CharField(max_length=40, choices=IDENTIFIER_TYPES, default="OTHER")
    value_hash = models.CharField(max_length=64, blank=True, default="")
    protected_value = models.TextField(blank=True, default="")
    last_four = models.CharField(max_length=4, blank=True, default="")
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUSES,
        default="UNVERIFIED",
    )
    issuing_authority = models.CharField(max_length=160, blank=True, default="")
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "identifier_type", "value_hash"],
                condition=~Q(value_hash=""),
                name="uq_patient_identifier_hash",
            ),
            models.UniqueConstraint(
                fields=["tenant", "system", "value"],
                condition=~Q(value=""),
                name="uq_patient_identifier_tenant",
            ),
        ]

    @property
    def masked_value(self):
        suffix = self.last_four or (self.value[-4:] if self.value else "")
        return f"••••{suffix}" if suffix else "PROTECTED"


class PatientAllergy(TenantConsistencyMixin, TimestampedModel):
    SEVERITY_INFO = "INFO"
    SEVERITY_WARNING = "WARNING"
    SEVERITY_HARD_STOP = "HARD_STOP"
    SEVERITY_CHOICES = (
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_HARD_STOP, "Hard stop"),
    )
    STATUS_CHOICES = (
        ("SUSPECTED", "Suspected"),
        ("CONFIRMED", "Confirmed"),
        ("REFUTED", "Refuted"),
        ("INACTIVE", "Inactive"),
    )
    VERIFICATION_CHOICES = (
        ("UNVERIFIED", "Unverified"),
        ("PATIENT_REPORTED", "Patient reported"),
        ("CLINICIAN_VERIFIED", "Clinician verified"),
    )
    tenant_relation_fields = ("patient", "active_ingredient")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="allergies")
    allergen_name = models.CharField(max_length=160)
    allergen_code = models.CharField(max_length=100, blank=True)
    allergen_system = models.CharField(max_length=255, blank=True)
    medicinal_product = models.ForeignKey(
        "medicines.Medicine",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    active_ingredient = models.ForeignKey(
        "cds.ActiveIngredient",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    reaction = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_WARNING)
    onset_date = models.DateField(null=True, blank=True)
    verification_status = models.CharField(
        max_length=30,
        choices=VERIFICATION_CHOICES,
        default="UNVERIFIED",
    )
    source = models.CharField(max_length=120, default="PATIENT_REPORTED")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="SUSPECTED")
    notes = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "patient", "is_active"], name="ix_patient_allergy_active"),
            models.Index(fields=["tenant", "allergen_name"], name="ix_patient_allergen"),
        ]

    def clean(self):
        super().clean()
        if self.medicinal_product_id and self.medicinal_product.tenant_id not in {
            None,
            self.tenant_id,
        }:
            raise ValidationError(
                {"medicinal_product": "Medicine is outside the patient tenant scope."}
            )


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


class PatientClinicalSummary(TenantConsistencyMixin, TimestampedModel):
    VERIFICATION_CHOICES = (
        ("UNVERIFIED", "Unverified"),
        ("PATIENT_REPORTED", "Patient reported"),
        ("CLINICIAN_VERIFIED", "Clinician verified"),
    )

    tenant_relation_fields = ("patient",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name="clinical_summary")
    pregnancy_status = models.CharField(max_length=40, default="NOT_RECORDED")
    lactation_status = models.CharField(max_length=40, default="NOT_RECORDED")
    renal_impairment = models.CharField(max_length=40, default="NOT_RECORDED")
    hepatic_impairment = models.CharField(max_length=40, default="NOT_RECORDED")
    height_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=120, default="NOT_RECORDED")
    verification_status = models.CharField(
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

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(height_cm__isnull=True) | Q(height_cm__gt=0),
                name="chk_patient_height_positive",
            ),
            models.CheckConstraint(
                condition=Q(weight_kg__isnull=True) | Q(weight_kg__gt=0),
                name="chk_patient_weight_positive",
            ),
        ]


class PatientConditionSummary(TenantConsistencyMixin, TimestampedModel):
    STATUS_CHOICES = (
        ("ACTIVE", "Active"),
        ("RESOLVED", "Resolved"),
        ("INACTIVE", "Inactive"),
    )

    tenant_relation_fields = ("patient",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="condition_summaries")
    code = models.CharField(max_length=120, blank=True, default="")
    code_system = models.CharField(max_length=255, blank=True, default="")
    description = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")
    onset_date = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=120)
    verification_status = models.CharField(max_length=30, default="UNVERIFIED")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(
                fields=["tenant", "patient", "status"],
                name="ix_patient_condition_active",
            )
        ]
