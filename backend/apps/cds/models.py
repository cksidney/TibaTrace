from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel
from apps.core.tenant_context import get_current_tenant_id


class ClinicalKnowledgeManager(models.Manager):
    def get_queryset(self):
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            return super().get_queryset().none()
        return super().get_queryset().filter(Q(tenant_id=tenant_id) | Q(tenant__isnull=True))

    def for_tenant(self, tenant):
        tenant_id = getattr(tenant, "pk", tenant)
        if not tenant_id:
            raise ValueError("A tenant is required for clinical knowledge access.")
        return super().get_queryset().filter(Q(tenant_id=tenant_id) | Q(tenant__isnull=True))


class ClinicalKnowledgeRelease(TimestampedModel):
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="knowledge_releases"
    )
    code = models.CharField(max_length=100)
    version = models.CharField(max_length=80)
    source = models.CharField(max_length=200)
    source_version = models.CharField(max_length=100)
    licence = models.CharField(max_length=200)
    effective_date = models.DateField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_global = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    content_classification = models.CharField(max_length=50, default="DEMONSTRATION")
    checksum_sha256 = models.CharField(max_length=64)

    objects = ClinicalKnowledgeManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code", "version"],
                condition=Q(tenant__isnull=False),
                name="uq_cds_release_tenant",
            ),
            models.UniqueConstraint(
                fields=["code", "version"],
                condition=Q(tenant__isnull=True, is_global=True),
                name="uq_cds_release_global",
            ),
            models.CheckConstraint(
                condition=Q(tenant__isnull=False, is_global=False) | Q(tenant__isnull=True, is_global=True),
                name="ck_cds_release_scope",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "is_active", "effective_date"], name="ix_cds_release_active")]

    def clean(self):
        super().clean()
        if self.is_global == bool(self.tenant_id):
            raise ValidationError("Knowledge release must be tenant-owned or explicitly global.")
        if self.content_classification not in {"DEMONSTRATION", "LICENSED_PRODUCTION"}:
            raise ValidationError({"content_classification": "Unsupported clinical content classification."})
        if len(self.checksum_sha256) != 64:
            raise ValidationError({"checksum_sha256": "A SHA-256 content checksum is required."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ActiveIngredient(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="active_ingredients")
    code = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    code_system = models.CharField(max_length=255, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_cds_ingredient_tenant")]


class MedicineIngredient(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("ingredient",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    medicine = models.ForeignKey("medicines.Medicine", on_delete=models.CASCADE, related_name="ingredient_links")
    ingredient = models.ForeignKey(ActiveIngredient, on_delete=models.PROTECT, related_name="medicine_links")
    strength_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    strength_unit = models.CharField(max_length=50, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "medicine", "ingredient"], name="uq_cds_medicine_ingredient")
        ]

    def clean(self):
        super().clean()
        if self.medicine_id and self.medicine.tenant_id not in {None, self.tenant_id}:
            raise ValidationError({"medicine": "Medicine is outside the tenant or global scope."})


class ClinicalKnowledgeRule(TimestampedModel):
    RULE_TYPES = (
        ("DRUG_DRUG", "Drug-drug interaction"),
        ("DRUG_DRUG_INTERACTION", "Drug-drug interaction"),
        ("ALLERGY", "Allergy"),
        ("DUPLICATE_THERAPY", "Duplicate therapy"),
        ("CONDITION", "Condition contraindication"),
        ("CONTRAINDICATION", "Contraindication"),
        ("AGE", "Age"),
        ("AGE_RESTRICTION", "Age restriction"),
        ("PREGNANCY", "Pregnancy"),
        ("PREGNANCY_WARNING", "Pregnancy warning"),
        ("LACTATION_WARNING", "Lactation warning"),
        ("RENAL", "Renal"),
        ("RENAL_IMPAIRMENT", "Renal impairment"),
        ("HEPATIC", "Hepatic"),
        ("HEPATIC_IMPAIRMENT", "Hepatic impairment"),
        ("DOSE", "Dose"),
        ("DOSE_TOO_HIGH", "Dose too high"),
        ("DOSE_TOO_LOW", "Dose too low"),
        ("WEIGHT_BASED_DOSE", "Weight-based dose"),
        ("MAXIMUM_DAILY_DOSE", "Maximum daily dose"),
        ("FREQUENCY_TOO_HIGH", "Frequency too high"),
        ("FREQUENCY_TOO_LOW", "Frequency too low"),
        ("DURATION", "Duration"),
        ("DURATION_TOO_LONG", "Duration too long"),
        ("DURATION_TOO_SHORT", "Duration too short"),
        ("CONTROLLED_MEDICINE_RULE", "Controlled medicine rule"),
        ("EARLY_REPEAT", "Early repeat"),
        ("LATE_REPEAT", "Late repeat"),
        ("THERAPEUTIC_DUPLICATION", "Therapeutic duplication"),
        ("FORMULARY_RESTRICTION", "Formulary restriction"),
        ("INSUFFICIENT_DATA", "Insufficient data"),
    )
    SEVERITIES = (
        ("INFO", "Info"),
        ("INFORMATION", "Information"),
        ("LOW", "Low"),
        ("WARNING", "Warning"),
        ("MODERATE", "Moderate"),
        ("HIGH", "High"),
        ("BLOCK", "Block"),
        ("CRITICAL", "Critical"),
    )
    OVERRIDE_POLICIES = (
        ("NONE", "No override required"),
        ("REASON", "Reason required"),
        ("PHARMACIST", "Pharmacist capability and reason required"),
        ("PROHIBITED", "Cannot override"),
    )

    release = models.ForeignKey(ClinicalKnowledgeRelease, on_delete=models.PROTECT, related_name="rules")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    rule_id = models.CharField(max_length=120)
    rule_version = models.CharField(max_length=80)
    rule_type = models.CharField(max_length=40, choices=RULE_TYPES)
    primary_code = models.CharField(max_length=120)
    interacting_code = models.CharField(max_length=120, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITIES)
    evidence_summary = models.TextField()
    explanation = models.TextField()
    recommended_action = models.TextField()
    override_policy = models.CharField(max_length=20, choices=OVERRIDE_POLICIES, default="PHARMACIST")
    criteria = models.JSONField(default=dict, blank=True)
    effective_date = models.DateField()
    is_active = models.BooleanField(default=True)

    objects = ClinicalKnowledgeManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["release", "rule_id", "rule_version"], name="uq_cds_rule_release")]
        indexes = [
            models.Index(fields=["tenant", "rule_type", "primary_code", "is_active"], name="ix_cds_rule_lookup"),
            models.Index(fields=["release", "rule_type", "interacting_code"], name="ix_cds_rule_factor"),
        ]

    def clean(self):
        super().clean()
        if self.release_id and self.tenant_id != self.release.tenant_id:
            raise ValidationError({"tenant": "Rule scope must match its knowledge release."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ClinicalEvaluation(TenantConsistencyMixin, TimestampedModel):
    STATUS_CHOICES = (
        ("PASS", "Pass"),
        ("WARNING", "Warning"),
        ("BLOCK", "Block"),
        ("KNOWLEDGE_UNAVAILABLE", "Knowledge unavailable"),
        ("ERROR", "Error"),
    )
    tenant_relation_fields = ("patient", "prescription")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="clinical_evaluations")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="clinical_evaluations")
    prescription = models.ForeignKey(
        "prescription.Prescription", on_delete=models.PROTECT, related_name="clinical_evaluations"
    )
    knowledge_release = models.ForeignKey(
        ClinicalKnowledgeRelease, on_delete=models.PROTECT, null=True, blank=True, related_name="evaluations"
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES)
    context_hash = models.CharField(max_length=64)
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="clinical_evaluations"
    )
    completed_at = models.DateTimeField(auto_now_add=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_detail = models.CharField(max_length=255, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "prescription", "created_at"], name="ix_cds_eval_prescription")]

    def clean(self):
        super().clean()
        if self.knowledge_release_id and self.knowledge_release.tenant_id not in {None, self.tenant_id}:
            raise ValidationError({"knowledge_release": "Knowledge release is outside the tenant scope."})


class ClinicalFinding(TenantConsistencyMixin, TimestampedModel):
    RESOLUTION_STATUSES = (
        ("OPEN", "Open"),
        ("ACKNOWLEDGED", "Acknowledged"),
        ("OVERRIDDEN", "Overridden"),
        ("INTERVENTION_REQUIRED", "Intervention required"),
        ("RESOLVED", "Resolved"),
        ("NOT_APPLICABLE", "Not applicable"),
    )
    tenant_relation_fields = (
        "evaluation",
        "patient",
        "prescription",
        "prescription_item",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="clinical_findings")
    evaluation = models.ForeignKey(ClinicalEvaluation, on_delete=models.CASCADE, related_name="findings")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    prescription = models.ForeignKey("prescription.Prescription", on_delete=models.PROTECT)
    prescription_item = models.ForeignKey(
        "prescription.PrescriptionItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="clinical_findings",
    )
    affected_medicine = models.ForeignKey(
        "medicines.Medicine", on_delete=models.PROTECT, null=True, blank=True, related_name="cds_findings"
    )
    rule_id = models.CharField(max_length=120)
    rule_version = models.CharField(max_length=80)
    rule_type = models.CharField(max_length=40)
    clinical_category = models.CharField(max_length=60, blank=True, default="")
    source = models.CharField(max_length=200)
    source_version = models.CharField(max_length=100)
    effective_date = models.DateField()
    severity = models.CharField(max_length=20)
    evidence_summary = models.TextField()
    explanation = models.TextField()
    recommended_action = models.TextField()
    override_policy = models.CharField(max_length=20)
    interacting_factor = models.CharField(max_length=255, blank=True, default="")
    resolution_status = models.CharField(
        max_length=30,
        choices=RESOLUTION_STATUSES,
        default="OPEN",
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    resolution_reason = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "evaluation",
                    "rule_id",
                    "rule_version",
                    "prescription_item",
                    "interacting_factor",
                ],
                name="uq_clinical_finding_issue",
            )
        ]
        indexes = [
            models.Index(
                fields=["tenant", "prescription", "resolution_status", "severity"],
                name="ix_cds_finding_resolution",
            )
        ]


class ClinicalOverride(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("finding", "prescription")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="clinical_overrides")
    finding = models.OneToOneField(ClinicalFinding, on_delete=models.PROTECT, related_name="override")
    prescription = models.ForeignKey("prescription.Prescription", on_delete=models.PROTECT)
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    clinical_justification = models.TextField(blank=True, default="")
    rule_version = models.CharField(max_length=80, blank=True, default="")
    supporting_evidence = models.JSONField(default=dict, blank=True)
    authorized_at = models.DateTimeField(auto_now_add=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def clean(self):
        if not self.clinical_justification and self.reason:
            self.clinical_justification = self.reason
        super().clean()
        if not str(self.reason or "").strip():
            raise ValidationError({"reason": "A clinical override reason is required."})
        if not str(self.clinical_justification or "").strip():
            raise ValidationError(
                {"clinical_justification": "Clinical justification is required."}
            )
        if self.finding_id and self.finding.override_policy == "PROHIBITED":
            raise ValidationError({"finding": "This finding cannot be overridden."})
        if self.authorized_by_id and not self.authorized_by.has_capability(
            "cds.override", tenant_id=self.tenant_id
        ):
            raise ValidationError({"authorized_by": "Clinical override capability is required."})

    def save(self, *args, **kwargs):
        if (
            self.pk
            and ClinicalOverride.all_objects.filter(
                tenant_id=self.tenant_id,
                pk=self.pk,
            ).exists()
        ):
            raise ValidationError("Clinical overrides are immutable.")
        if self.finding_id and not self.rule_version:
            self.rule_version = self.finding.rule_version
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Clinical overrides cannot be deleted.")


from apps.cds.pos_screening_models import (  # noqa: E402, F401
    PosClinicalAuditEvent,
    PosClinicalDecision,
    PosClinicalFinding,
    PosClinicalOverride,
    PosClinicalScreening,
)
