from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
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
    lookup_key_id = models.CharField(max_length=64, blank=True, default="", editable=False)
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

    @classmethod
    def matching_value(cls, *, tenant_id, value, system=None, identifier_type=None):
        """Internal tenant-scoped exact lookup across retained digest versions."""
        from apps.patients.identifier_crypto import SYSTEM_SCOPED_TYPES
        from apps.patients.identifier_crypto import PatientIdentifierProtector as protector

        normalized = protector.normalize(value)
        _, _, lookup, _, legacy = protector.configuration()
        known_versions = [*lookup, ""] if legacy else list(lookup)
        tenant_rows = cls.all_objects.filter(tenant_id=tenant_id, patient__tenant_id=tenant_id)
        if tenant_rows.exclude(lookup_key_id__in=known_versions).exists():
            raise ValidationError("Historical identifier lookup keys are unavailable. Restore the retained keys or complete migration.")
        condition = Q(value=str(value).strip())
        types = [identifier_type] if identifier_type else [choice[0] for choice in cls.IDENTIFIER_TYPES]
        for kind in types:
            systems = [system] if system is not None else (tenant_rows.filter(identifier_type=kind).values_list("system", flat=True).distinct() if kind in SYSTEM_SCOPED_TYPES else [""])
            for namespace in systems:
                versions, historical = protector.lookup_digests(tenant_id=tenant_id, identifier_type=kind, value=value, system=namespace)
                clause = Q(identifier_type=kind, value_hash__in=[*versions.values(), *historical])
                if kind in SYSTEM_SCOPED_TYPES:
                    clause &= Q(system=namespace)
                condition |= clause
                if kind not in SYSTEM_SCOPED_TYPES:
                    condition |= Q(identifier_type=kind, value=normalized)
        rows = tenant_rows.filter(condition)
        if system is not None:
            rows = rows.filter(system=system)
        if identifier_type:
            rows = rows.filter(identifier_type=identifier_type)
        return rows

    def value_for_exchange(self):
        """Internal converter access; caller must enforce exchange/read authority."""
        from apps.patients.identifier_crypto import PatientIdentifierProtector

        return PatientIdentifierProtector.verified_plaintext(self)

    @transaction.atomic
    def save(self, *args, **kwargs):
        from apps.patients.identifier_crypto import SYSTEM_SCOPED_TYPES
        from apps.patients.identifier_crypto import PatientIdentifierProtector as protector
        from apps.tenancy.models import Tenant

        # Serializes identity writes/rotation without conflicting with tenant
        # foreign-key key-share locks held by concurrent patient intake.
        if not self.tenant_id:
            raise ValidationError("Patient identifier tenant scope is required.")
        Tenant.objects.select_for_update(no_key=True).get(pk=self.tenant_id)
        _, _, lookup, _, legacy = protector.configuration()
        known_versions = [*lookup, ""] if legacy else list(lookup)
        others = PatientIdentifier.all_objects.filter(tenant_id=self.tenant_id).exclude(pk=self.pk)
        if others.exclude(lookup_key_id__in=known_versions).exists():
            raise ValidationError("Historical identifier lookup keys are unavailable. Complete key provisioning or migration before identity writes.")
        plaintext = protector.verified_plaintext(self)
        versions, historical = protector.lookup_digests(tenant_id=self.tenant_id, identifier_type=self.identifier_type, value=plaintext, system=self.system)
        duplicates = others.filter(identifier_type=self.identifier_type)
        if self.identifier_type in SYSTEM_SCOPED_TYPES:
            duplicates = duplicates.filter(system=self.system)
        if duplicates.filter(
            Q(value_hash__in=[*versions.values(), *historical]) | Q(value=self.value) & ~Q(value="")
        ).exists():
            raise ValidationError("This patient identifier is already registered in the tenant.")
        for old in duplicates.filter(lookup_key_id=""):
            old_value = protector.verified_plaintext(old)
            matches = old_value == plaintext if self.identifier_type in SYSTEM_SCOPED_TYPES else protector.normalize(old_value) == protector.normalize(plaintext)
            if matches:
                raise ValidationError("This patient identifier is already registered in the tenant.")
        crypto_fields = ("value", "protected_value", "value_hash", "lookup_key_id", "last_four")
        if self.value or not self.protected_value or not self.value_hash:
            for field, value in protector.storage_fields(tenant_id=self.tenant_id, identifier_type=self.identifier_type, value=plaintext, system=self.system).items():
                setattr(self, field, value)
        elif not self.lookup_key_id:
            # Compatible with callers that prepared a new versioned ciphertext
            # before the lookup-version field was supplied.
            self.lookup_key_id = next((kid for kid, digest in versions.items() if digest == self.value_hash), "")
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | set(crypto_fields)
        return super().save(*args, **kwargs)


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
