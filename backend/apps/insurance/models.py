from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import (
    StrictTenantManager,
    TenantConsistencyMixin,
    TimestampedModel,
)

# ==============================================================================
# 1. INSURER & SCHEME GOVERNANCE MODELS
# ==============================================================================

class Insurer(TenantConsistencyMixin, TimestampedModel):
    class InsurerType(models.TextChoices):
        PRIVATE = "PRIVATE", _("Private Medical Insurer")
        PUBLIC = "PUBLIC", _("Public Health Financing Scheme (e.g. SHA)")
        EMPLOYER = "EMPLOYER", _("Employer-Funded Scheme")
        TPA = "TPA", _("Third-Party Administrator")
        COMMUNITY = "COMMUNITY", _("Community Mutual Fund")

    class IntegrationAdapter(models.TextChoices):
        FAKE = "FAKE", _("Deterministic Test Fake Adapter")
        SHA = "SHA", _("Social Health Authority (SHA) Kenya")
        PRIVATE_REST = "PRIVATE_REST", _("Generic Private Insurer REST API")
        BATCH_FILE = "BATCH_FILE", _("SFTP / Batch File Export")
        MANUAL_PORTAL = "MANUAL_PORTAL", _("Manual Portal Submission")

    class Environment(models.TextChoices):
        SANDBOX = "SANDBOX", _("Sandbox / Test Environment")
        PRODUCTION = "PRODUCTION", _("Production Environment")

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        SUSPENDED = "SUSPENDED", _("Suspended")
        INACTIVE = "INACTIVE", _("Inactive")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    code = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    insurer_type = models.CharField(max_length=32, choices=InsurerType.choices, default=InsurerType.PRIVATE)
    regulatory_identifier = models.CharField(max_length=128, blank=True, default="")
    integration_adapter = models.CharField(max_length=64, choices=IntegrationAdapter.choices, default=IntegrationAdapter.FAKE)
    environment = models.CharField(max_length=32, choices=Environment.choices, default=Environment.SANDBOX)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=64, blank=True, default="")
    submission_mode = models.CharField(max_length=32, default="REALTIME")
    preauth_mode = models.CharField(max_length=32, default="AUTOMATIC")
    eligibility_mode = models.CharField(max_length=32, default="REALTIME")
    settlement_currency = models.CharField(max_length=3, default="KES")

    tenant_relation_fields = ()
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uq_insurer_tenant_code")
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="ix_insurer_tenant_status")
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class InsurerScheme(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.CASCADE, related_name="schemes")
    code = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, default="ACTIVE")

    tenant_relation_fields = ("insurer",)
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["insurer", "code"], name="uq_insurerscheme_code")
        ]

    def __str__(self):
        return f"{self.name} [{self.code}]"


class InsurerPlan(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    scheme = models.ForeignKey(InsurerScheme, on_delete=models.CASCADE, related_name="plans")
    code = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    plan_class = models.CharField(max_length=64, default="STANDARD")
    status = models.CharField(max_length=32, default="ACTIVE")

    tenant_relation_fields = ("scheme",)
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scheme", "code"], name="uq_insurerplan_code")
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class InsurerProviderContract(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.CASCADE, related_name="contracts")
    branch = models.ForeignKey("organizations.Location", on_delete=models.CASCADE, related_name="+")
    contract_number = models.CharField(max_length=128)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    tenant_relation_fields = ("insurer", "branch")
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["insurer", "branch", "contract_number"], name="uq_contract_number")
        ]

    def __str__(self):
        return f"Contract #{self.contract_number} ({self.insurer.code})"


class InsurerEndpointConfiguration(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.CASCADE, related_name="endpoints")
    environment = models.CharField(max_length=32, default="SANDBOX")
    endpoint_type = models.CharField(max_length=64)
    base_url = models.URLField()
    timeout_seconds = models.IntegerField(default=15)
    retry_count = models.IntegerField(default=3)

    tenant_relation_fields = ("insurer",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class InsurerCredentialReference(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.CASCADE, related_name="credentials")
    secret_reference = models.CharField(max_length=255)
    credential_type = models.CharField(max_length=64, default="API_KEY")
    is_active = models.BooleanField(default=True)

    tenant_relation_fields = ("insurer",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


# ==============================================================================
# 2. MEMBER COVERAGE MODELS
# ==============================================================================

class InsuranceMember(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    membership_number = models.CharField(max_length=128, db_index=True)
    principal_name = models.CharField(max_length=255)
    national_id = models.CharField(max_length=64, blank=True, default="")
    passport_number = models.CharField(max_length=64, blank=True, default="")
    contact_phone = models.CharField(max_length=64, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    status = models.CharField(max_length=32, default="ACTIVE")

    tenant_relation_fields = ()
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "membership_number"], name="uq_member_tenant_number")
        ]

    def __str__(self):
        return f"{self.principal_name} [{self.membership_number}]"


class InsuranceCoverage(TenantConsistencyMixin, TimestampedModel):
    class Relationship(models.TextChoices):
        SELF = "SELF", _("Principal Member")
        SPOUSE = "SPOUSE", _("Spouse")
        CHILD = "CHILD", _("Child")
        PARENT = "PARENT", _("Parent")
        OTHER = "OTHER", _("Other Dependent")

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active Coverage")
        EXPIRED = "EXPIRED", _("Expired Coverage")
        SUSPENDED = "SUSPENDED", _("Suspended Coverage")
        CANCELLED = "CANCELLED", _("Cancelled")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    member = models.ForeignKey(InsuranceMember, on_delete=models.CASCADE, related_name="coverages")
    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="insurance_coverages")
    scheme = models.ForeignKey(InsurerScheme, on_delete=models.PROTECT, related_name="+")
    plan = models.ForeignKey(InsurerPlan, on_delete=models.PROTECT, related_name="+")
    dependent_code = models.CharField(max_length=32, default="00")
    relationship = models.CharField(max_length=32, choices=Relationship.choices, default=Relationship.SELF)
    valid_from = models.DateField()
    valid_to = models.DateField()
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    remaining_limit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("50000.00"))
    copay_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    coinsurance_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    deductible = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))

    tenant_relation_fields = ("member", "patient", "scheme", "plan")
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["member", "patient", "plan"], name="uq_coverage_member_patient_plan")
        ]

    def __str__(self):
        return f"Coverage for {self.patient} under {self.scheme.name}"


class InsuranceDependent(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    member = models.ForeignKey(InsuranceMember, on_delete=models.CASCADE, related_name="dependents")
    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="+")
    dependent_code = models.CharField(max_length=32)
    relationship = models.CharField(max_length=32, default="CHILD")
    full_name = models.CharField(max_length=255)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=16, blank=True, default="")

    tenant_relation_fields = ("member", "patient")
    objects = StrictTenantManager()
    all_objects = models.Manager()


class CoverageBenefit(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    plan = models.ForeignKey(InsurerPlan, on_delete=models.CASCADE, related_name="benefits")
    category = models.CharField(max_length=64, default="OUTPATIENT_MEDICINE")
    covered = models.BooleanField(default=True)
    requires_preauth = models.BooleanField(default=False)
    copay_rule = models.CharField(max_length=128, blank=True, default="")
    coinsurance_rule = models.CharField(max_length=128, blank=True, default="")
    benefit_limit = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    tenant_relation_fields = ("plan",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class CoverageLimit(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    coverage = models.ForeignKey(InsuranceCoverage, on_delete=models.CASCADE, related_name="limits")
    category = models.CharField(max_length=64, default="OUTPATIENT_PHARMACY")
    total_limit = models.DecimalField(max_digits=15, decimal_places=2)
    used_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    remaining_amount = models.DecimalField(max_digits=15, decimal_places=2)
    reset_date = models.DateField(null=True, blank=True)

    tenant_relation_fields = ("coverage",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class CoverageExclusion(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    plan = models.ForeignKey(InsurerPlan, on_delete=models.CASCADE, related_name="exclusions")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    active_substance = models.ForeignKey("medicines.ActiveSubstance", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    exclusion_reason = models.TextField(blank=True, default="")

    tenant_relation_fields = ("plan",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class CoverageVerification(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.CASCADE, related_name="+")
    member = models.ForeignKey(InsuranceMember, on_delete=models.CASCADE, related_name="+")
    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="+")
    verification_reference = models.CharField(max_length=128, unique=True)
    is_eligible = models.BooleanField(default=True)
    eligibility_status = models.CharField(max_length=64, default="ACTIVE")
    verified_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    raw_response_digest = models.CharField(max_length=128, blank=True, default="")

    tenant_relation_fields = ("insurer", "member", "patient")
    objects = StrictTenantManager()
    all_objects = models.Manager()


# ==============================================================================
# 3. PREAUTHORISATION MODELS
# ==============================================================================

class PrescriptionPreauthorisation(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        READY = "READY", _("Ready for Request")
        SUBMITTED = "SUBMITTED", _("Submitted")
        PENDING = "PENDING", _("Pending Insurer Decision")
        MORE_INFO_REQUIRED = "MORE_INFO_REQUIRED", _("More Information Required")
        PARTIALLY_APPROVED = "PARTIALLY_APPROVED", _("Partially Approved")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")
        EXPIRED = "EXPIRED", _("Expired")
        CANCELLED = "CANCELLED", _("Cancelled")
        REVERSED = "REVERSED", _("Reversed")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    preauth_number = models.CharField(max_length=64, db_index=True)
    episode = models.ForeignKey("prescription.DispensingEpisode", on_delete=models.CASCADE, related_name="preauthorisations")
    prescription = models.ForeignKey("prescription.Prescription", on_delete=models.CASCADE, related_name="+")
    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    total_claimed = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    total_approved = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    authorization_code = models.CharField(max_length=128, blank=True, default="")
    decision_notes = models.TextField(blank=True, default="")

    tenant_relation_fields = ("episode", "prescription", "patient", "insurer")
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "preauth_number"], name="uq_preauth_number")
        ]

    def __str__(self):
        return f"Preauth #{self.preauth_number} [{self.status}]"


class PreauthorisationLine(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        APPROVED = "APPROVED", _("Approved")
        PARTIALLY_APPROVED = "PARTIALLY_APPROVED", _("Partially Approved")
        REJECTED = "REJECTED", _("Rejected")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    preauthorisation = models.ForeignKey(PrescriptionPreauthorisation, on_delete=models.CASCADE, related_name="lines")
    prescription_item = models.ForeignKey("prescription.PrescriptionItem", on_delete=models.CASCADE, related_name="+")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    requested_quantity = models.DecimalField(max_digits=15, decimal_places=4)
    approved_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=Decimal("0.0000"))
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.TextField(blank=True, default="")

    tenant_relation_fields = ("preauthorisation", "prescription_item", "sku")
    objects = StrictTenantManager()
    all_objects = models.Manager()


class PreauthorisationAttempt(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    preauthorisation = models.ForeignKey(PrescriptionPreauthorisation, on_delete=models.CASCADE, related_name="attempts")
    attempt_number = models.IntegerField(default=1)
    idempotency_key = models.CharField(max_length=255, unique=True)
    request_payload_digest = models.CharField(max_length=128, blank=True, default="")
    response_payload_digest = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=32, default="COMPLETED")

    tenant_relation_fields = ("preauthorisation",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class PreauthorisationDecision(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    preauthorisation = models.ForeignKey(PrescriptionPreauthorisation, on_delete=models.CASCADE, related_name="decisions")
    decision_code = models.CharField(max_length=64)
    decision_by = models.CharField(max_length=128, blank=True, default="")
    decision_timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")

    tenant_relation_fields = ("preauthorisation",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class PreauthorisationAttachment(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    preauthorisation = models.ForeignKey(PrescriptionPreauthorisation, on_delete=models.CASCADE, related_name="attachments")
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=64)
    storage_path = models.CharField(max_length=512)
    content_hash = models.CharField(max_length=128)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    tenant_relation_fields = ("preauthorisation",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


# ==============================================================================
# 4. PRESCRIPTION CLAIM & ADJUDICATION MODELS
# ==============================================================================

class PrescriptionClaim(TenantConsistencyMixin, TimestampedModel):
    class SubmissionState(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        VALIDATING = "VALIDATING", _("Validating")
        VALIDATION_FAILED = "VALIDATION_FAILED", _("Validation Failed")
        READY_TO_SUBMIT = "READY_TO_SUBMIT", _("Ready to Submit")
        SUBMITTED = "SUBMITTED", _("Submitted")
        TRANSPORT_ACCEPTED = "TRANSPORT_ACCEPTED", _("Transport Accepted (HTTP 200)")
        TRANSPORT_REJECTED = "TRANSPORT_REJECTED", _("Transport Rejected")

    class AdjudicationState(models.TextChoices):
        PENDING = "PENDING", _("Pending Adjudication")
        MORE_INFO_REQUIRED = "MORE_INFO_REQUIRED", _("More Info Required")
        PARTIALLY_APPROVED = "PARTIALLY_APPROVED", _("Partially Approved")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")
        REVERSED = "REVERSED", _("Reversed")

    class PaymentState(models.TextChoices):
        UNPAID = "UNPAID", _("Unpaid")
        PARTIALLY_PAID = "PARTIALLY_PAID", _("Partially Paid")
        PAID = "PAID", _("Fully Paid")

    class ReconciliationState(models.TextChoices):
        UNRECONCILED = "UNRECONCILED", _("Unreconciled")
        PARTIALLY_MATCHED = "PARTIALLY_MATCHED", _("Partially Matched")
        MATCHED = "MATCHED", _("Matched")
        EXCEPTION = "EXCEPTION", _("Reconciliation Exception")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim_number = models.CharField(max_length=64, db_index=True)
    episode = models.ForeignKey("prescription.DispensingEpisode", on_delete=models.CASCADE, related_name="claims")
    prescription = models.ForeignKey("prescription.Prescription", on_delete=models.CASCADE, related_name="+")
    supply = models.ForeignKey("prescription.MedicineSupply", on_delete=models.PROTECT, related_name="claims")
    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="+")
    member = models.ForeignKey(InsuranceMember, on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name="+")
    scheme = models.ForeignKey(InsurerScheme, on_delete=models.PROTECT, related_name="+")
    preauthorisation = models.ForeignKey(PrescriptionPreauthorisation, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    submission_state = models.CharField(max_length=32, choices=SubmissionState.choices, default=SubmissionState.DRAFT, db_index=True)
    adjudication_state = models.CharField(max_length=32, choices=AdjudicationState.choices, default=AdjudicationState.PENDING, db_index=True)
    payment_state = models.CharField(max_length=32, choices=PaymentState.choices, default=PaymentState.UNPAID, db_index=True)
    reconciliation_state = models.CharField(max_length=32, choices=ReconciliationState.choices, default=ReconciliationState.UNRECONCILED, db_index=True)

    claimed_gross_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    claimed_net_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    approved_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    patient_copay_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    insurer_payable_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="KES")

    tenant_relation_fields = ("episode", "prescription", "supply", "patient", "member", "insurer", "scheme")
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "claim_number"], name="uq_claim_number")
        ]
        indexes = [
            models.Index(fields=["tenant", "submission_state"], name="ix_claim_submission_state"),
            models.Index(fields=["tenant", "adjudication_state"], name="ix_claim_adjudication_state"),
        ]

    def __str__(self):
        return f"Claim #{self.claim_number} [{self.submission_state}/{self.adjudication_state}]"


class PrescriptionClaimLine(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="lines")
    prescription_line = models.ForeignKey("prescription.DispensingLine", on_delete=models.CASCADE, related_name="+")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    insurer_item_code = models.CharField(max_length=128, blank=True, default="")
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    claimed_amount = models.DecimalField(max_digits=15, decimal_places=2)
    approved_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    disallowed_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=32, default="SUBMITTED")
    rejection_code = models.CharField(max_length=64, blank=True, default="")

    tenant_relation_fields = ("claim", "prescription_line", "sku")
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimDiagnosis(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="diagnoses")
    diagnosis_code = models.CharField(max_length=64)
    diagnosis_description = models.CharField(max_length=255)
    is_primary = models.BooleanField(default=True)
    source = models.CharField(max_length=64, default="PRESCRIPTION")

    tenant_relation_fields = ("claim",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimAttachment(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="attachments")
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=64)
    storage_path = models.CharField(max_length=512)
    content_hash = models.CharField(max_length=128)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    tenant_relation_fields = ("claim",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimSubmissionAttempt(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="attempts")
    attempt_number = models.IntegerField(default=1)
    idempotency_key = models.CharField(max_length=255, unique=True)
    payload_digest = models.CharField(max_length=128, blank=True, default="")
    transport_status = models.CharField(max_length=64, default="TRANSPORT_ACCEPTED")
    # What the insurer decided, kept apart from whether the message arrived.
    # Without this the attempt records only that bytes were delivered, and a
    # provider reading it cannot tell an approval from silence -- which is how
    # a receivable gets booked against a claim nobody agreed to pay.
    business_status = models.CharField(max_length=64, default="UNKNOWN")
    external_reference = models.CharField(max_length=255, blank=True, default="")
    response_code = models.CharField(max_length=64, blank=True, default="")
    response_message = models.TextField(blank=True, default="")
    # Whether this failure may be retried. A timeout may; a refusal may not,
    # and retrying one produces a duplicate claim.
    retryable = models.BooleanField(default=False)
    response_payload_digest = models.CharField(max_length=128, blank=True, default="")
    attempted_at = models.DateTimeField(auto_now_add=True)

    tenant_relation_fields = ("claim",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimProviderResponse(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="responses")
    response_code = models.CharField(max_length=64)
    response_message = models.TextField(blank=True, default="")
    raw_body_digest = models.CharField(max_length=128, blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)

    tenant_relation_fields = ("claim",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimAdjudication(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.OneToOneField(PrescriptionClaim, on_delete=models.CASCADE, related_name="adjudication")
    adjudication_number = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=32, default="APPROVED")
    approved_amount = models.DecimalField(max_digits=15, decimal_places=2)
    disallowed_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    patient_liability = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    insurer_liability = models.DecimalField(max_digits=15, decimal_places=2)
    adjudicated_at = models.DateTimeField(auto_now_add=True)
    reason_notes = models.TextField(blank=True, default="")

    tenant_relation_fields = ("claim",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimAdjudicationLine(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    adjudication = models.ForeignKey(ClaimAdjudication, on_delete=models.CASCADE, related_name="lines")
    claim_line = models.ForeignKey(PrescriptionClaimLine, on_delete=models.CASCADE, related_name="+")
    claimed_amount = models.DecimalField(max_digits=15, decimal_places=2)
    allowed_amount = models.DecimalField(max_digits=15, decimal_places=2)
    approved_amount = models.DecimalField(max_digits=15, decimal_places=2)
    patient_liability = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    insurer_liability = models.DecimalField(max_digits=15, decimal_places=2)
    disallowed_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    reason_code = models.CharField(max_length=64, blank=True, default="")

    tenant_relation_fields = ("adjudication", "claim_line")
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimAdjustment(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="adjustments")
    adjustment_type = models.CharField(max_length=64)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    tenant_relation_fields = ("claim",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimRejection(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="rejections")
    rejection_code = models.CharField(max_length=64)
    reason_description = models.TextField()
    resubmission_eligible = models.BooleanField(default=True)
    operator_action = models.CharField(max_length=128, blank=True, default="")
    resolved = models.BooleanField(default=False)

    tenant_relation_fields = ("claim",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimResubmission(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    original_claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="resubmissions_from")
    new_claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="resubmissions_to")
    resubmission_reason = models.TextField()
    resubmitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    resubmitted_at = models.DateTimeField(auto_now_add=True)

    tenant_relation_fields = ("original_claim", "new_claim")
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimReversal(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.ForeignKey(PrescriptionClaim, on_delete=models.CASCADE, related_name="reversals")
    reversal_number = models.CharField(max_length=64, unique=True)
    reason = models.TextField()
    status = models.CharField(max_length=32, default="COMPLETED")
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reversed_at = models.DateTimeField(auto_now_add=True)

    tenant_relation_fields = ("claim",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


# ==============================================================================
# 5. REMITTANCE & RECONCILIATION MODELS
# ==============================================================================

class InsuranceRemittance(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    remittance_number = models.CharField(max_length=64, db_index=True)
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name="+")
    total_remitted_amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_reference = models.CharField(max_length=128)
    remittance_date = models.DateField()
    status = models.CharField(max_length=32, default="PROCESSED")

    tenant_relation_fields = ("insurer",)
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "remittance_number"], name="uq_remittance_number")
        ]


class InsuranceRemittanceLine(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    remittance = models.ForeignKey(InsuranceRemittance, on_delete=models.CASCADE, related_name="lines")
    # Nullable, because insurers send payment lines naming claim references we
    # do not hold -- a typo, another provider's claim, or a claim raised in a
    # system we have since replaced. That money physically arrived. Forcing a
    # claim here would mean either dropping the line or attaching the payment to
    # the wrong claim, and both are worse than recording it as unmatched for
    # somebody to investigate.
    claim = models.ForeignKey(
        PrescriptionClaim, on_delete=models.PROTECT, null=True, blank=True,
        related_name="remittance_lines",
    )
    claimed_amount = models.DecimalField(max_digits=15, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2)
    adjustment_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=32, default="MATCHED")

    tenant_relation_fields = ("remittance", "claim")
    objects = StrictTenantManager()
    all_objects = models.Manager()


class InsurancePayment(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    remittance = models.ForeignKey(InsuranceRemittance, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    payment_reference = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date = models.DateField()
    currency = models.CharField(max_length=3, default="KES")
    tender_type = models.CharField(max_length=64, default="BANK_TRANSFER")

    tenant_relation_fields = ("remittance",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class InsurancePaymentAllocation(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    payment = models.ForeignKey(InsurancePayment, on_delete=models.CASCADE, related_name="allocations")
    claim = models.ForeignKey(PrescriptionClaim, on_delete=models.PROTECT, related_name="payment_allocations")
    allocated_amount = models.DecimalField(max_digits=15, decimal_places=2)
    allocated_at = models.DateTimeField(auto_now_add=True)

    tenant_relation_fields = ("payment", "claim")
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimReconciliation(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    claim = models.OneToOneField(PrescriptionClaim, on_delete=models.CASCADE, related_name="reconciliation")
    remittance = models.ForeignKey(InsuranceRemittance, on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=32, default="MATCHED")
    reconciled_amount = models.DecimalField(max_digits=15, decimal_places=2)
    variance_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))
    reconciled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reconciled_at = models.DateTimeField(auto_now_add=True)

    tenant_relation_fields = ("claim", "remittance")
    objects = StrictTenantManager()
    all_objects = models.Manager()


class ClaimReconciliationException(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    # Also nullable: the most important exception to raise is an unidentifiable
    # payment, which by definition has no claim to point at.
    claim = models.ForeignKey(
        PrescriptionClaim, on_delete=models.CASCADE, null=True, blank=True,
        related_name="exceptions",
    )
    remittance = models.ForeignKey(InsuranceRemittance, on_delete=models.CASCADE, related_name="+")
    exception_type = models.CharField(max_length=64)
    variance_amount = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.TextField(blank=True, default="")
    resolved = models.BooleanField(default=False)

    tenant_relation_fields = ("claim", "remittance")
    objects = StrictTenantManager()
    all_objects = models.Manager()


# ==============================================================================
# 6. MEDICINE CLAIM CODING & OUTBOX/INBOX
# ==============================================================================

class MedicineClaimCodeMap(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.CASCADE, related_name="code_maps")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.CASCADE, related_name="+")
    insurer_item_code = models.CharField(max_length=128)
    insurer_item_name = models.CharField(max_length=255)
    is_covered = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    tenant_relation_fields = ("insurer", "sku")
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["insurer", "sku"], name="uq_claim_code_map")
        ]


class ClaimCodeMappingVersion(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.CASCADE, related_name="+")
    version_number = models.IntegerField(default=1)
    effective_from = models.DateField()
    status = models.CharField(max_length=32, default="ACTIVE")

    tenant_relation_fields = ("insurer",)
    objects = StrictTenantManager()
    all_objects = models.Manager()


class UnmappedClaimItem(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.CASCADE, related_name="+")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.CASCADE, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, default="PENDING_MAPPING")

    tenant_relation_fields = ("insurer", "sku")
    objects = StrictTenantManager()
    all_objects = models.Manager()


class InsuranceOutboxMessage(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    event_type = models.CharField(max_length=128)
    correlation_id = models.UUIDField(default=uuid.uuid4)
    idempotency_key = models.CharField(max_length=255, unique=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=32, default="PENDING")
    retry_count = models.IntegerField(default=0)

    tenant_relation_fields = ()
    objects = StrictTenantManager()
    all_objects = models.Manager()


class InsuranceInboxMessage(TenantConsistencyMixin, TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    source_insurer = models.ForeignKey(Insurer, on_delete=models.CASCADE, related_name="+")
    external_event_id = models.CharField(max_length=255, unique=True)
    payload_digest = models.CharField(max_length=128)
    processing_status = models.CharField(max_length=32, default="PROCESSED")
    received_at = models.DateTimeField(auto_now_add=True)

    tenant_relation_fields = ("source_insurer",)
    objects = StrictTenantManager()
    all_objects = models.Manager()
