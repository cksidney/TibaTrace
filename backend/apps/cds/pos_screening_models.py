import uuid

from django.conf import settings
from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class PosClinicalScreening(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETE = "COMPLETE", "Complete"
        INCOMPLETE_DATA = "INCOMPLETE_DATA", "Incomplete data"
        OFFLINE_CACHE = "OFFLINE_CACHE", "Offline cache"
        FAILED = "FAILED", "Failed"
        STALE = "STALE", "Stale"
        INVALIDATED = "INVALIDATED", "Invalidated"

    class Severity(models.TextChoices):
        INFORMATION = "INFORMATION", "Information"
        LOW = "LOW", "Low"
        MODERATE = "MODERATE", "Moderate"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    screening_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    transaction_id = models.CharField(max_length=128, db_index=True)
    device_id = models.CharField(max_length=128)
    register_id = models.CharField(max_length=128, blank=True, default="")
    branch_id = models.UUIDField(null=True, blank=True)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    prescription = models.ForeignKey(
        "prescription.Prescription", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    dispensing_episode_id = models.CharField(max_length=128, blank=True, default="")
    context_hash = models.CharField(max_length=128, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    highest_severity = models.CharField(max_length=32, choices=Severity.choices, null=True, blank=True)
    blocking_count = models.IntegerField(default=0)
    requires_pharmacist = models.BooleanField(default=False)
    safe_to_proceed = models.BooleanField(default=False)
    rule_set_version = models.CharField(max_length=64, blank=True, default="")
    evaluated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    offline_state = models.BooleanField(default=False)
    screening_mode = models.CharField(max_length=64, default="STRICT")
    idempotency_key = models.CharField(max_length=128, blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "transaction_id", "context_hash"], name="uq_pos_screening_tx_ctx"
            )
        ]
        indexes = [models.Index(fields=["tenant", "status"], name="ix_pos_screening_tenant_status")]

    def __str__(self):
        return f"POS Screening {self.screening_id} [{self.status}]"


class PosClinicalFinding(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("screening",)

    class Category(models.TextChoices):
        DRUG_DRUG_INTERACTION = "DRUG_DRUG_INTERACTION", "Drug-drug interaction"
        DRUG_ALLERGY = "DRUG_ALLERGY", "Drug allergy"
        DUPLICATE_THERAPY = "DUPLICATE_THERAPY", "Duplicate therapy"
        CONTRAINDICATION = "CONTRAINDICATION", "Contraindication"
        DOSE_TOO_HIGH = "DOSE_TOO_HIGH", "Dose too high"
        DOSE_TOO_LOW = "DOSE_TOO_LOW", "Dose too low"
        FREQUENCY_TOO_HIGH = "FREQUENCY_TOO_HIGH", "Frequency too high"
        FREQUENCY_TOO_LOW = "FREQUENCY_TOO_LOW", "Frequency too low"
        DURATION_TOO_LONG = "DURATION_TOO_LONG", "Duration too long"
        DURATION_TOO_SHORT = "DURATION_TOO_SHORT", "Duration too short"
        AGE_RESTRICTION = "AGE_RESTRICTION", "Age restriction"
        WEIGHT_BASED_DOSE = "WEIGHT_BASED_DOSE", "Weight-based dose"
        RENAL_IMPAIRMENT = "RENAL_IMPAIRMENT", "Renal impairment"
        HEPATIC_IMPAIRMENT = "HEPATIC_IMPAIRMENT", "Hepatic impairment"
        PREGNANCY_WARNING = "PREGNANCY_WARNING", "Pregnancy warning"
        LACTATION_WARNING = "LACTATION_WARNING", "Lactation warning"
        CONTROLLED_MEDICINE_RULE = "CONTROLLED_MEDICINE_RULE", "Controlled medicine rule"
        EARLY_REPEAT = "EARLY_REPEAT", "Early repeat"
        THERAPEUTIC_DUPLICATION = "THERAPEUTIC_DUPLICATION", "Therapeutic duplication"
        MAXIMUM_DAILY_DOSE = "MAXIMUM_DAILY_DOSE", "Maximum daily dose"
        FORMULARY_RESTRICTION = "FORMULARY_RESTRICTION", "Formulary restriction"
        PRESCRIPTION_REQUIRED = "PRESCRIPTION_REQUIRED", "Prescription required"
        PHARMACIST_VERIFICATION_REQUIRED = "PHARMACIST_VERIFICATION_REQUIRED", "Pharmacist verification required"
        INSUFFICIENT_PATIENT_DATA = "INSUFFICIENT_PATIENT_DATA", "Insufficient patient data"
        STALE_CLINICAL_DATA = "STALE_CLINICAL_DATA", "Stale clinical data"
        OFFLINE_SCREENING_UNAVAILABLE = "OFFLINE_SCREENING_UNAVAILABLE", "Offline screening unavailable"

    class ResolutionStatus(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        PHARMACIST_REVIEWED = "PHARMACIST_REVIEWED", "Pharmacist reviewed"
        OVERRIDDEN = "OVERRIDDEN", "Overridden"
        RESOLVED = "RESOLVED", "Resolved"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    screening = models.ForeignKey(PosClinicalScreening, on_delete=models.CASCADE, related_name="findings")
    rule = models.ForeignKey(
        "cds.ClinicalKnowledgeRule", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    rule_id_ref = models.CharField(max_length=128, blank=True, default="")
    rule_version = models.CharField(max_length=64, blank=True, default="")
    category = models.CharField(max_length=64, choices=Category.choices)
    severity = models.CharField(max_length=32, choices=PosClinicalScreening.Severity.choices)
    title = models.CharField(max_length=255)
    summary = models.TextField()
    clinical_explanation = models.TextField(blank=True, default="")
    recommendation = models.TextField(blank=True, default="")
    affected_basket_line_ids = models.JSONField(default=list, blank=True)
    affected_medicine_ids = models.JSONField(default=list, blank=True)
    patient_context_required = models.BooleanField(default=False)
    blocking = models.BooleanField(default=False)
    requires_pharmacist = models.BooleanField(default=False)
    override_allowed = models.BooleanField(default=True)
    override_capability = models.CharField(max_length=128, blank=True, default="")
    evidence_source = models.CharField(max_length=255, blank=True, default="")
    detected_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    resolution_status = models.CharField(
        max_length=32, choices=ResolutionStatus.choices, default=ResolutionStatus.OPEN
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["screening", "severity"], name="ix_pos_finding_screening_sev"),
            models.Index(fields=["screening", "resolution_status"], name="ix_pos_finding_screening_res"),
        ]

    def __str__(self):
        return f"{self.category} [{self.severity}] - {self.title}"


class PosClinicalDecision(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("screening",)

    class Decision(models.TextChoices):
        APPROVE = "APPROVE", "Approve"
        APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS", "Approve with conditions"
        RETURN_FOR_CORRECTION = "RETURN_FOR_CORRECTION", "Return for correction"
        REJECT = "REJECT", "Reject"
        CONTACT_PRESCRIBER = "CONTACT_PRESCRIBER", "Contact prescriber"
        REQUIRE_ALTERNATIVE = "REQUIRE_ALTERNATIVE", "Require alternative"
        REQUEST_MORE_INFORMATION = "REQUEST_MORE_INFORMATION", "Request more information"

        # Retained for previously persisted client payloads. New POS screens use
        # the canonical review vocabulary above.
        APPROVE_AS_WRITTEN = "APPROVE_AS_WRITTEN", "Approve as written"
        APPROVE_WITH_COUNSELLING = "APPROVE_WITH_COUNSELLING", "Approve with counselling"
        REMOVE_MEDICINE = "REMOVE_MEDICINE", "Remove medicine"
        CHANGE_QUANTITY = "CHANGE_QUANTITY", "Change quantity"
        APPROVED_SUBSTITUTION = "APPROVED_SUBSTITUTION", "Approved substitution"
        PRESCRIBER_CLARIFICATION_REQUIRED = "PRESCRIBER_CLARIFICATION_REQUIRED", "Prescriber clarification required"
        PATIENT_CLARIFICATION_REQUIRED = "PATIENT_CLARIFICATION_REQUIRED", "Patient clarification required"
        HOLD_TRANSACTION = "HOLD_TRANSACTION", "Hold transaction"
        REJECT_SUPPLY = "REJECT_SUPPLY", "Reject supply"
        AUTHORIZED_OVERRIDE = "AUTHORIZED_OVERRIDE", "Authorized override"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    screening = models.ForeignKey(PosClinicalScreening, on_delete=models.CASCADE, related_name="decisions")
    finding = models.ForeignKey(
        PosClinicalFinding, on_delete=models.SET_NULL, null=True, blank=True, related_name="decisions"
    )
    pharmacist = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decision = models.CharField(max_length=64, choices=Decision.choices)
    clinical_justification = models.TextField(blank=True, default="")
    conditions = models.TextField(blank=True, default="")
    counselling_notes = models.TextField(blank=True, default="")
    prescriber_contact_ref = models.CharField(max_length=255, blank=True, default="")
    follow_up_actions = models.TextField(blank=True, default="")
    context_hash_at_decision = models.CharField(max_length=128)
    rule_version_at_decision = models.CharField(max_length=64, blank=True, default="")
    branch_id = models.UUIDField(null=True, blank=True)
    transaction_id = models.CharField(max_length=128, blank=True, default="")
    register_id = models.CharField(max_length=128, blank=True, default="")
    patient_ref = models.CharField(max_length=128, blank=True, default="")
    prescription_ref = models.CharField(max_length=128, blank=True, default="")
    idempotency_key = models.CharField(max_length=128, unique=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"Decision: {self.decision} by {self.pharmacist}"


class PosClinicalOverride(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("decision",)

    class OverrideReason(models.TextChoices):
        KNOWN_AND_MONITORED = "KNOWN_AND_MONITORED", "Known and monitored"
        CLINICALLY_JUSTIFIED = "CLINICALLY_JUSTIFIED", "Clinically justified"
        PRESCRIBER_CONFIRMED = "PRESCRIBER_CONFIRMED", "Prescriber confirmed"
        PATIENT_ALREADY_STABLE = "PATIENT_ALREADY_STABLE", "Patient already stable"
        DOSE_ADJUSTED = "DOSE_ADJUSTED", "Dose adjusted"
        DUPLICATION_INTENTIONAL = "DUPLICATION_INTENTIONAL", "Duplication intentional"
        SHORT_DURATION = "SHORT_DURATION", "Short duration"
        PALLIATIVE_CARE = "PALLIATIVE_CARE", "Palliative care"
        SPECIALIST_INSTRUCTION = "SPECIALIST_INSTRUCTION", "Specialist instruction"
        OTHER = "OTHER", "Other"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    decision = models.ForeignKey(PosClinicalDecision, on_delete=models.CASCADE, related_name="overrides")
    finding = models.ForeignKey(PosClinicalFinding, on_delete=models.PROTECT, related_name="overrides")
    pharmacist = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    override_reason = models.CharField(max_length=64, choices=OverrideReason.choices)
    clinical_justification = models.TextField()
    override_capability = models.CharField(max_length=128)
    context_hash = models.CharField(max_length=128)
    rule_version = models.CharField(max_length=64, blank=True, default="")
    transaction_id = models.CharField(max_length=128)
    device_id = models.CharField(max_length=128)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"Override: {self.override_reason} for {self.finding}"


class PosOfflineClinicalPackage(TenantConsistencyMixin, TimestampedModel):
    class SigningVersion(models.TextChoices):
        #: The original scheme keyed the HMAC on tenant.pk, which is public
        #: metadata. Anyone holding a tenant UUID could mint a package that
        #: verified, so packages signed this way prove nothing about their
        #: origin and are rejected on sight. Retained as a value only so that
        #: historical records can be classified and audited.
        LEGACY_TENANT_UUID_HMAC = "LEGACY_TENANT_UUID_HMAC", "Legacy (forgeable)"
        OBJECT_SIGNING_KEY_V1 = "OBJECT_SIGNING_KEY_V1", "Object signing key v1"

    #: Only these may ever verify. LEGACY is deliberately absent.
    SUPPORTED_SIGNING_VERSIONS = frozenset({SigningVersion.OBJECT_SIGNING_KEY_V1})

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    version = models.CharField(max_length=64)
    rule_set_version = models.CharField(max_length=64, blank=True, default="")
    package_data = models.JSONField(default=dict)
    signature = models.CharField(max_length=512)
    signing_version = models.CharField(
        max_length=40,
        choices=SigningVersion.choices,
        default=SigningVersion.OBJECT_SIGNING_KEY_V1,
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # Binding: a package is valid only for the exact context it was issued for.
    branch = models.ForeignKey(
        "organizations.Location",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    device_id = models.CharField(max_length=128, blank=True, default="")
    context_hash = models.CharField(max_length=64, blank=True, default="")
    #: Unique per issuance, so two packages can never be byte-identical and a
    #: captured signature cannot be replayed onto a fresh record.
    nonce = models.UUIDField(default=uuid.uuid4, editable=False)

    # Revocation. Old packages are kept for audit rather than deleted.
    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=120, blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "version"], name="uq_pos_offline_pkg_version")
        ]

    def __str__(self):
        return f"Offline Package v{self.version} [{self.rule_set_version}]"


class PosClinicalAuditEvent(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("screening", "finding")

    class EventType(models.TextChoices):
        SCREENING_REQUESTED = "SCREENING_REQUESTED", "Screening requested"
        SCREENING_COMPLETED = "SCREENING_COMPLETED", "Screening completed"
        FINDING_DISPLAYED = "FINDING_DISPLAYED", "Finding displayed"
        FINDING_ACKNOWLEDGED = "FINDING_ACKNOWLEDGED", "Finding acknowledged"
        PHARMACIST_REVIEW_REQUESTED = "PHARMACIST_REVIEW_REQUESTED", "Pharmacist review requested"
        PHARMACIST_AUTHENTICATED = "PHARMACIST_AUTHENTICATED", "Pharmacist authenticated"
        FINDING_RESOLVED = "FINDING_RESOLVED", "Finding resolved"
        OVERRIDE_RECORDED = "OVERRIDE_RECORDED", "Override recorded"
        SCREENING_INVALIDATED = "SCREENING_INVALIDATED", "Screening invalidated"
        OFFLINE_SCREENING_USED = "OFFLINE_SCREENING_USED", "Offline screening used"
        SCREENING_UNAVAILABLE = "SCREENING_UNAVAILABLE", "Screening unavailable"
        TRANSACTION_BLOCKED = "TRANSACTION_BLOCKED", "Transaction blocked"
        TRANSACTION_RELEASED = "TRANSACTION_RELEASED", "Transaction released"
        CLINICAL_CONTEXT_STALE = "CLINICAL_CONTEXT_STALE", "Clinical context stale"
        CLINICAL_CAPABILITY_DENIED = "CLINICAL_CAPABILITY_DENIED", "Clinical capability denied"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    branch_id = models.UUIDField(null=True, blank=True)
    device_id = models.CharField(max_length=128, blank=True, default="")
    register_id = models.CharField(max_length=128, blank=True, default="")
    transaction_id = models.CharField(max_length=128, blank=True, default="")
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    pharmacist = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    patient_ref = models.CharField(max_length=128, blank=True, default="")
    prescription_ref = models.CharField(max_length=128, blank=True, default="")
    screening = models.ForeignKey(
        PosClinicalScreening, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    finding = models.ForeignKey(
        PosClinicalFinding, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    severity = models.CharField(max_length=32, blank=True, default="")
    rule_version = models.CharField(max_length=64, blank=True, default="")
    context_hash = models.CharField(max_length=128, blank=True, default="")
    online_state = models.BooleanField(default=True)
    correlation_id = models.UUIDField(default=uuid.uuid4)
    payload = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "event_type"], name="ix_pos_audit_tenant_type"),
            models.Index(fields=["tenant", "transaction_id"], name="ix_pos_audit_tenant_tx"),
            models.Index(fields=["correlation_id"], name="ix_pos_audit_correlation"),
        ]

    def __str__(self):
        return f"{self.event_type} [{self.transaction_id}]"
