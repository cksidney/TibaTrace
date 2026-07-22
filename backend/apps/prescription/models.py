from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class Prescription(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("patient", "practitioner", "organization", "location")

    STATUS_CHOICES = (
        ("DRAFT", "Draft"),
        ("ISSUED", "Issued"),
        ("VERIFIED", "Verified"),
        ("DISPENSED_PARTIALLY", "Dispensed partially"),
        ("DISPENSED", "Dispensed"),
        ("EXPIRED", "Expired"),
        ("CANCELLED", "Cancelled"),
        ("REJECTED", "Rejected"),
        ("SUSPENDED", "Suspended"),
        ("COMPLETED", "Completed"),
    )
    WORKFLOW_STATES = (
        ("DRAFT", "Draft"),
        ("CLINICAL_REVIEW", "Clinical review"),
        ("BLOCKED", "Blocked"),
        ("APPROVED", "Approved"),
        ("DISPENSING", "Dispensing"),
        ("READY_FOR_PAYMENT", "Ready for payment"),
        ("PAID", "Paid"),
        ("DISPENSED", "Dispensed"),
        ("REVERSED", "Reversed"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="prescriptions")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="prescriptions")
    practitioner = models.ForeignKey("practitioners.Practitioner", on_delete=models.PROTECT, related_name="prescriptions")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="prescriptions")
    location = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="prescriptions")
    prescription_number = models.CharField(max_length=80)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="DRAFT")
    workflow_state = models.CharField(max_length=50, choices=WORKFLOW_STATES, default="DRAFT")
    issued_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    substitution_policy = models.CharField(max_length=50, default="ALLOWED")
    clinical_context_hash = models.CharField(max_length=64, blank=True)
    clinical_review_id = models.UUIDField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="prescriptions_clinically_approved",
    )
    payment_reference = models.CharField(max_length=160, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "prescription_number"], name="uq_prescription_number_tenant")
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="ix_prescription_tenant_status"),
            models.Index(fields=["tenant", "workflow_state"], name="ix_prescription_workflow"),
            models.Index(fields=["tenant", "patient"], name="ix_prescription_patient"),
        ]

    def clean(self):
        super().clean()
        if self.issued_at and self.expires_at and self.expires_at <= self.issued_at:
            raise ValidationError({"expires_at": "Prescription expiry must be after issue time."})
        if self.location_id and self.organization_id and self.location.organization_id != self.organization_id:
            raise ValidationError({"location": "Location must belong to the prescription organization."})


class PrescriptionItem(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("prescription",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    canonical_medicine = models.ForeignKey("medicines.Medicine", on_delete=models.PROTECT, null=True, blank=True)
    medication_name = models.CharField(max_length=255)
    dosage_instruction = models.TextField()
    dose_amount = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    dose_unit = models.CharField(max_length=50, blank=True)
    frequency_per_day = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    refills_authorized = models.PositiveIntegerField(default=0)
    is_controlled = models.BooleanField(default=False)
    route = models.CharField(max_length=80, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    @property
    def total_authorized_quantity(self) -> Decimal:
        return self.quantity * Decimal(self.refills_authorized + 1)

    def clean(self):
        super().clean()
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({"quantity": "Prescription quantity must be positive."})
        if self.canonical_medicine_id and self.canonical_medicine.tenant_id not in {None, self.tenant_id}:
            raise ValidationError({"canonical_medicine": "Medicine is outside the prescription tenant scope."})


class PrescriptionDispense(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("prescription", "location")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(Prescription, on_delete=models.PROTECT, related_name="dispenses")
    location = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="dispenses")
    dispensed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50, default="COMPLETED")
    dispensed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    idempotency_key = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uq_dispense_idempotency_tenant")
        ]


class PrescriptionFill(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("dispense", "item")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    dispense = models.ForeignKey(PrescriptionDispense, on_delete=models.CASCADE, related_name="fills")
    item = models.ForeignKey(PrescriptionItem, on_delete=models.PROTECT, related_name="fills")
    quantity_dispensed = models.DecimalField(max_digits=12, decimal_places=3)
    substituted_medicine = models.ForeignKey("medicines.Medicine", on_delete=models.PROTECT, null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def clean(self):
        super().clean()
        if self.quantity_dispensed is None or self.quantity_dispensed <= 0:
            raise ValidationError({"quantity_dispensed": "Dispensed quantity must be positive."})
        if self.substituted_medicine_id and self.substituted_medicine.tenant_id not in {None, self.tenant_id}:
            raise ValidationError({"substituted_medicine": "Substitute medicine is outside the tenant scope."})


class PrescriptionStatusHistory(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("prescription",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="history")
    status = models.CharField(max_length=50)
    workflow_state = models.CharField(max_length=50)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    reason = models.TextField(blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class PrescriptionWorkflowEvent(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("prescription",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="workflow_events")
    from_state = models.CharField(max_length=50)
    to_state = models.CharField(max_length=50)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    reason = models.TextField(blank=True)
    context_hash = models.CharField(max_length=64, blank=True)
    correlation_id = models.CharField(max_length=100, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class PrescriptionVerification(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("prescription",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="verifications")
    verified_by_provider = models.CharField(max_length=100)
    verification_payload = models.JSONField(default=dict)
    is_valid = models.BooleanField(default=False)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class PrescriptionAudit(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("prescription",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="audit_events")
    event_type = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    device_id = models.CharField(max_length=100, blank=True)
    correlation_id = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class PrescriptionSubstitution(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("fill", "original_item")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    fill = models.ForeignKey(PrescriptionFill, on_delete=models.CASCADE)
    original_item = models.ForeignKey(PrescriptionItem, on_delete=models.PROTECT)
    substitute_medicine = models.ForeignKey("medicines.Medicine", on_delete=models.PROTECT)
    reason = models.CharField(max_length=255)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def clean(self):
        super().clean()
        if self.substitute_medicine_id and self.substitute_medicine.tenant_id not in {None, self.tenant_id}:
            raise ValidationError({"substitute_medicine": "Substitute medicine is outside the tenant scope."})
        if not str(self.reason or "").strip():
            raise ValidationError({"reason": "A substitution reason is required."})


class ProviderConfiguration(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="provider_configurations")
    provider_code = models.CharField(max_length=50)
    base_url = models.URLField()
    auth_type = models.CharField(max_length=50)
    credential_reference = models.CharField(max_length=255, blank=True)
    certificate_id = models.CharField(max_length=255, blank=True)
    rate_limit = models.PositiveIntegerField(default=100)
    retry_policy = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "provider_code"], name="uq_provider_config_tenant")
        ]


class IntegrationOutbox(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="integration_outbox")
    provider_code = models.CharField(max_length=50)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    correlation_id = models.CharField(max_length=255)
    status = models.CharField(max_length=50, default="PENDING")
    retry_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "correlation_id"], name="uq_integration_correlation_tenant"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uq_integration_idempotency_tenant"),
        ]


class DeadLetterQueue(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("outbox_item",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="dead_letters")
    outbox_item = models.OneToOneField(IntegrationOutbox, on_delete=models.CASCADE)
    reason = models.TextField()
    failed_at = models.DateTimeField(auto_now_add=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()
