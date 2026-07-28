from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class Prescription(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = (
        "patient",
        "practitioner",
        "organization",
        "location",
        "prescribing_organization",
        "original_document",
    )

    STATUS_CHOICES = (
        ("DRAFT", "Draft"),
        ("RECEIVED", "Received"),
        ("INTAKE_REVIEW", "Intake review"),
        ("LEGALLY_VALIDATED", "Legally validated"),
        ("CLINICAL_REVIEW", "Clinical review"),
        ("PHARMACIST_VERIFIED", "Pharmacist verified"),
        ("READY_FOR_DISPENSING", "Ready for dispensing"),
        ("ISSUED", "Issued"),
        ("VERIFIED", "Verified"),
        ("DISPENSED_PARTIALLY", "Dispensed partially"),
        ("PARTIALLY_SUPPLIED", "Partially supplied"),
        ("SUPPLIED", "Supplied"),
        ("CLOSED", "Closed"),
        ("ON_HOLD", "On hold"),
        ("INTERVENTION_REQUIRED", "Intervention required"),
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
    PRESCRIPTION_TYPES = (
        ("ACUTE", "Acute"),
        ("REPEAT", "Repeat"),
        ("CHRONIC", "Chronic"),
        ("CONTROLLED", "Controlled"),
        ("DISCHARGE", "Discharge"),
        ("EMERGENCY", "Emergency"),
        ("VETERINARY", "Veterinary"),
        ("INTERNAL", "Internal"),
    )
    SOURCE_CHANNELS = (
        ("PAPER", "Paper"),
        ("ELECTRONIC", "Electronic"),
        ("PORTAL", "Portal"),
        ("HOSPITAL_INTEGRATION", "Hospital integration"),
        ("MOBILE", "Mobile"),
        ("TRANSFERRED", "Transferred"),
    )
    LEGAL_STATES = (
        ("PENDING", "Pending"),
        ("PASSED", "Passed"),
        ("FAILED", "Failed"),
        ("MANUAL_REVIEW", "Manual review"),
    )
    REVIEW_STATES = (
        ("NOT_STARTED", "Not started"),
        ("IN_PROGRESS", "In progress"),
        ("FINDINGS_OPEN", "Findings open"),
        ("COMPLETED", "Completed"),
        ("BLOCKED", "Blocked"),
    )
    VERIFICATION_STATES = (
        ("NOT_VERIFIED", "Not verified"),
        ("VERIFIED", "Verified"),
        ("REVOKED", "Revoked"),
    )
    DISPENSING_STATES = (
        ("NOT_STARTED", "Not started"),
        ("READY", "Ready"),
        ("PARTIALLY_DISPENSED", "Partially dispensed"),
        ("DISPENSED", "Dispensed"),
        ("PARTIALLY_SUPPLIED", "Partially supplied"),
        ("SUPPLIED", "Supplied"),
        ("RETURNED", "Returned"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="prescriptions")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="prescriptions")
    practitioner = models.ForeignKey("practitioners.Practitioner", on_delete=models.PROTECT, related_name="prescriptions")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="prescriptions")
    location = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="prescriptions")
    prescription_number = models.CharField(max_length=80)
    external_prescription_reference = models.CharField(max_length=160, blank=True, default="")
    prescribing_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    prescription_date = models.DateField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    prescription_type = models.CharField(
        max_length=30,
        choices=PRESCRIPTION_TYPES,
        default="ACUTE",
    )
    source_channel = models.CharField(
        max_length=30,
        choices=SOURCE_CHANNELS,
        default="PAPER",
    )
    original_document = models.ForeignKey(
        "documents.StoredClinicalDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="DRAFT")
    workflow_state = models.CharField(max_length=50, choices=WORKFLOW_STATES, default="DRAFT")
    issued_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    substitution_policy = models.CharField(max_length=50, default="ALLOWED")
    is_controlled_medicine = models.BooleanField(default=False)
    repeat_authorization = models.BooleanField(default=False)
    repeats_allowed = models.PositiveIntegerField(default=0)
    repeats_remaining = models.PositiveIntegerField(default=0)
    legal_validation_state = models.CharField(
        max_length=30,
        choices=LEGAL_STATES,
        default="PENDING",
    )
    clinical_review_state = models.CharField(
        max_length=30,
        choices=REVIEW_STATES,
        default="NOT_STARTED",
    )
    pharmacist_verification_state = models.CharField(
        max_length=30,
        choices=VERIFICATION_STATES,
        default="NOT_VERIFIED",
    )
    dispensing_state = models.CharField(
        max_length=30,
        choices=DISPENSING_STATES,
        default="NOT_STARTED",
    )
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
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
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
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "prescription_number"], name="uq_prescription_number_tenant"),
            models.UniqueConstraint(
                fields=["tenant", "external_prescription_reference"],
                condition=~Q(external_prescription_reference=""),
                name="uq_prescription_external_ref",
            ),
            models.CheckConstraint(
                condition=Q(repeats_remaining__lte=F("repeats_allowed")),
                name="chk_prescription_repeat_balance",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__isnull=True)
                | Q(issued_at__isnull=True)
                | Q(expires_at__gt=F("issued_at")),
                name="chk_prescription_validity_order",
            ),
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

    def save(self, *args, **kwargs):
        material_fields = (
            "patient_id",
            "practitioner_id",
            "prescribing_organization_id",
            "prescription_date",
            "prescription_type",
            "original_document_id",
            "issued_at",
            "expires_at",
            "is_controlled_medicine",
            "repeat_authorization",
            "repeats_allowed",
        )
        material_change = False
        if self.pk:
            previous = (
                Prescription.all_objects.filter(
                    tenant_id=self.tenant_id,
                    pk=self.pk,
                )
                .values(*material_fields)
                .first()
            )
            material_change = bool(
                previous
                and any(
                    previous[field] != getattr(self, field)
                    for field in material_fields
                )
            )
        if material_change:
            self.pharmacist_verification_state = "REVOKED"
            self.clinical_review_state = "NOT_STARTED"
            self.dispensing_state = "NOT_STARTED"
            self.status = "CLINICAL_REVIEW"
        super().save(*args, **kwargs)
        if material_change:
            revoked = PharmacistVerification.all_objects.filter(
                tenant_id=self.tenant_id,
                prescription_id=self.id,
                revoked_at__isnull=True,
            ).update(
                revoked_at=timezone.now(),
                revoked_reason="Material prescription context changed.",
            )
            if revoked:
                from apps.workflows.service import emit_event

                emit_event(
                    tenant_id=self.tenant_id,
                    aggregate_type="Prescription",
                    aggregate_id=self.id,
                    event_type="PrescriptionVerificationRevoked",
                    payload={
                        "tenant": str(self.tenant_id),
                        "prescription": str(self.id),
                        "reason": "Material prescription context changed.",
                        "event_version": 1,
                        "timestamp": timezone.now().isoformat(),
                    },
                )


class PrescriptionItem(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("prescription",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    canonical_medicine = models.ForeignKey("medicines.Medicine", on_delete=models.PROTECT, null=True, blank=True)
    prescribed_medicinal_product = models.ForeignKey(
        "medicines.ClinicalMedicinalProduct",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    prescribed_brand = models.ForeignKey(
        "medicines.ManufacturedMedicinalProduct",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    prescribed_sku = models.ForeignKey(
        "medicines.CommercialSKU",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    medication_name = models.CharField(max_length=255)
    prescribed_description_snapshot = models.CharField(max_length=500, blank=True, default="")
    active_ingredient_snapshot = models.JSONField(default=list, blank=True)
    strength_snapshot = models.CharField(max_length=120, blank=True, default="")
    dosage_form_snapshot = models.CharField(max_length=120, blank=True, default="")
    dosage_instruction = models.TextField()
    dose_amount = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    dose_unit = models.CharField(max_length=50, blank=True)
    frequency_per_day = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=50, default="EA")
    refills_authorized = models.PositiveIntegerField(default=0)
    repeats_remaining = models.PositiveIntegerField(default=0)
    quantity_supplied_total = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    minimum_repeat_interval_days = models.PositiveIntegerField(default=0)
    earliest_refill_date = models.DateField(null=True, blank=True)
    latest_refill_date = models.DateField(null=True, blank=True)
    is_controlled = models.BooleanField(default=False)
    route = models.CharField(max_length=80, blank=True)
    indication = models.CharField(max_length=255, blank=True, default="")
    special_instructions = models.TextField(blank=True, default="")
    maximum_daily_dose = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    substitution_policy = models.CharField(max_length=80, default="NO_SUBSTITUTION")
    status = models.CharField(max_length=30, default="ACTIVE")
    clinical_notes = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="chk_rx_item_qty_positive"),
            models.CheckConstraint(
                condition=Q(quantity_supplied_total__gte=0),
                name="chk_rx_item_supplied_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(repeats_remaining__lte=F("refills_authorized")),
                name="chk_rx_item_repeat_balance",
            ),
            models.CheckConstraint(
                condition=Q(end_date__isnull=True)
                | Q(start_date__isnull=True)
                | Q(end_date__gte=F("start_date")),
                name="chk_rx_item_date_order",
            ),
        ]

    @property
    def total_authorized_quantity(self) -> Decimal:
        return self.quantity * Decimal(self.refills_authorized + 1)

    def clean(self):
        super().clean()
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({"quantity": "Prescription quantity must be positive."})
        if self.canonical_medicine_id and self.canonical_medicine.tenant_id not in {None, self.tenant_id}:
            raise ValidationError({"canonical_medicine": "Medicine is outside the prescription tenant scope."})
        if self.prescribed_sku_id and self.prescribed_sku.tenant_id != self.tenant_id:
            raise ValidationError({"prescribed_sku": "SKU is outside the prescription tenant scope."})
        if self.maximum_daily_dose is not None and self.maximum_daily_dose <= 0:
            raise ValidationError({"maximum_daily_dose": "Maximum daily dose must be positive."})

    def save(self, *args, **kwargs):
        material_fields = (
            "canonical_medicine_id",
            "prescribed_medicinal_product_id",
            "prescribed_brand_id",
            "prescribed_sku_id",
            "medication_name",
            "dosage_instruction",
            "dose_amount",
            "dose_unit",
            "frequency_per_day",
            "duration_days",
            "quantity",
            "route",
            "maximum_daily_dose",
        )
        material_change = False
        if self.pk:
            previous = (
                PrescriptionItem.all_objects.filter(
                    tenant_id=self.tenant_id,
                    pk=self.pk,
                )
                .values(*material_fields)
                .first()
            )
            material_change = bool(
                previous
                and any(previous[field] != getattr(self, field) for field in material_fields)
            )
            if material_change and MedicineSupplyLine.all_objects.filter(
                tenant_id=self.tenant_id,
                prescription_item_id=self.id,
            ).exists():
                raise ValidationError(
                    "Supplied prescription instructions are immutable; create a corrected prescription."
                )
        super().save(*args, **kwargs)
        if material_change:
            revoked = PharmacistVerification.all_objects.filter(
                tenant_id=self.tenant_id,
                prescription_id=self.prescription_id,
                revoked_at__isnull=True,
            ).update(
                revoked_at=timezone.now(),
                revoked_reason="Material prescription instruction changed.",
            )
            Prescription.all_objects.filter(
                tenant_id=self.tenant_id,
                pk=self.prescription_id,
            ).update(
                pharmacist_verification_state="REVOKED",
                clinical_review_state="NOT_STARTED",
                dispensing_state="NOT_STARTED",
            )
            if revoked:
                from apps.workflows.service import emit_event

                emit_event(
                    tenant_id=self.tenant_id,
                    aggregate_type="Prescription",
                    aggregate_id=self.prescription_id,
                    event_type="PrescriptionVerificationRevoked",
                    payload={
                        "tenant": str(self.tenant_id),
                        "prescription": str(self.prescription_id),
                        "prescription_item": str(self.id),
                        "reason": "Material prescription instruction changed.",
                        "event_version": 1,
                        "timestamp": timezone.now().isoformat(),
                    },
                )


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


class PrescriptionValidationFinding(TenantConsistencyMixin, TimestampedModel):
    SEVERITY_CHOICES = (
        ("INFORMATION", "Information"),
        ("LOW", "Low"),
        ("MODERATE", "Moderate"),
        ("HIGH", "High"),
        ("CRITICAL", "Critical"),
    )
    STATUS_CHOICES = (
        ("OPEN", "Open"),
        ("ACKNOWLEDGED", "Acknowledged"),
        ("RESOLVED", "Resolved"),
        ("NOT_APPLICABLE", "Not applicable"),
    )

    tenant_relation_fields = ("prescription", "prescription_item")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="validation_findings",
    )
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="validation_findings",
    )
    finding_code = models.CharField(max_length=80)
    category = models.CharField(max_length=80)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    message = models.TextField()
    source = models.CharField(max_length=120, default="PRESCRIPTION_VALIDATION")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="OPEN")
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
                fields=["prescription", "prescription_item", "finding_code"],
                name="uq_rx_validation_finding",
            )
        ]
        indexes = [
            models.Index(
                fields=["tenant", "status", "severity"],
                name="ix_rx_validation_queue",
            )
        ]


class PharmacistClinicalReview(TenantConsistencyMixin, TimestampedModel):
    OUTCOME_CHOICES = (
        ("APPROVED", "Approved"),
        ("APPROVED_WITH_COUNSELLING", "Approved with counselling"),
        ("INTERVENTION_REQUIRED", "Intervention required"),
        ("PRESCRIBER_CONTACT_REQUIRED", "Prescriber contact required"),
        ("PATIENT_CONTACT_REQUIRED", "Patient contact required"),
        ("REJECTED", "Rejected"),
        ("ON_HOLD", "On hold"),
    )

    tenant_relation_fields = ("prescription",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="pharmacist_reviews",
    )
    reviewing_pharmacist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    review_started_at = models.DateTimeField(default=timezone.now)
    review_completed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=50, choices=OUTCOME_CHOICES, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    verification_decision = models.CharField(max_length=40, blank=True, default="")
    context_hash = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["prescription", "version"],
                name="uq_pharmacist_review_version",
            )
        ]
        indexes = [
            models.Index(
                fields=["tenant", "review_completed_at"],
                name="ix_pharmacist_review_queue",
            )
        ]


class PharmacistIntervention(TenantConsistencyMixin, TimestampedModel):
    INTERVENTION_TYPES = (
        ("CLARIFICATION", "Clarification"),
        ("DOSE_CHANGE", "Dose change"),
        ("MEDICINE_CHANGE", "Medicine change"),
        ("DURATION_CHANGE", "Duration change"),
        ("FREQUENCY_CHANGE", "Frequency change"),
        ("FORM_CHANGE", "Form change"),
        ("SUBSTITUTION_APPROVAL", "Substitution approval"),
        ("STOP_MEDICINE", "Stop medicine"),
        ("COUNSELLING_ONLY", "Counselling only"),
        ("OTHER", "Other"),
    )
    STATUS_CHOICES = (
        ("OPEN", "Open"),
        ("AWAITING_RESPONSE", "Awaiting response"),
        ("RESOLVED", "Resolved"),
        ("CANCELLED", "Cancelled"),
    )

    tenant_relation_fields = (
        "prescription",
        "prescription_item",
        "review",
        "supporting_document",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="interventions",
    )
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="interventions",
    )
    review = models.ForeignKey(
        PharmacistClinicalReview,
        on_delete=models.PROTECT,
        related_name="interventions",
    )
    clinical_finding = models.ForeignKey(
        "cds.ClinicalFinding",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    intervention_type = models.CharField(max_length=40, choices=INTERVENTION_TYPES)
    contacted_party = models.CharField(max_length=120, blank=True, default="")
    contact_method = models.CharField(max_length=40, blank=True, default="")
    intervention_request = models.TextField()
    response = models.TextField(blank=True, default="")
    original_instruction = models.JSONField(default=dict, blank=True)
    changed_instruction = models.JSONField(default=dict, blank=True)
    prescriber_authorization = models.JSONField(default=dict, blank=True)
    outcome = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="OPEN")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    supporting_document = models.ForeignKey(
        "documents.StoredClinicalDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class PharmacistVerification(TenantConsistencyMixin, TimestampedModel):
    DECISION_CHOICES = (
        ("VERIFIED", "Verified"),
        ("VERIFIED_WITH_COUNSELLING", "Verified with counselling"),
    )

    tenant_relation_fields = ("prescription", "review")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="pharmacist_verifications",
    )
    review = models.ForeignKey(
        PharmacistClinicalReview,
        on_delete=models.PROTECT,
        related_name="verifications",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    decision = models.CharField(max_length=40, choices=DECISION_CHOICES)
    context_hash = models.CharField(max_length=64)
    verification_checks = models.JSONField(default=dict)
    clinical_justification = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=255)
    verified_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uq_pharmacist_verify_key",
            ),
            models.UniqueConstraint(
                fields=["prescription"],
                condition=Q(revoked_at__isnull=True),
                name="uq_active_rx_verification",
            ),
        ]

    def save(self, *args, **kwargs):
        if (
            self.pk
            and PharmacistVerification.all_objects.filter(
                tenant_id=self.tenant_id,
                pk=self.pk,
            ).exists()
        ):
            raise ValidationError("Pharmacist verification records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Pharmacist verification records cannot be deleted.")


class ClinicalSubstitution(TenantConsistencyMixin, TimestampedModel):
    STATUS_CHOICES = (
        ("PROPOSED", "Proposed"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled"),
    )

    tenant_relation_fields = (
        "prescription",
        "prescription_item",
        "proposed_sku",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="clinical_substitutions",
    )
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.PROTECT,
        related_name="clinical_substitutions",
    )
    prescribed_sku = models.ForeignKey(
        "medicines.CommercialSKU",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    proposed_sku = models.ForeignKey(
        "medicines.CommercialSKU",
        on_delete=models.PROTECT,
        related_name="+",
    )
    equivalence_basis = models.TextField()
    price_impact = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    stock_reason = models.TextField(blank=True, default="")
    prescriber_approved = models.BooleanField(default=False)
    patient_consented = models.BooleanField(default=False)
    pharmacist_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PROPOSED")
    reason = models.TextField()

    objects = StrictTenantManager()
    all_objects = models.Manager()


class DispensingEpisode(TenantConsistencyMixin, TimestampedModel):
    STATUS_CHOICES = (
        ("DRAFT", "Draft"),
        ("PREPARING", "Preparing"),
        ("CHECKING", "Checking"),
        ("READY_FOR_PAYMENT", "Ready for payment"),
        ("PAID", "Paid"),
        ("READY_FOR_COLLECTION", "Ready for collection"),
        ("READY_FOR_SUPPLY", "Ready for supply"),
        ("PARTIALLY_SUPPLIED", "Partially supplied"),
        ("SUPPLIED", "Supplied"),
        ("CLOSED", "Closed"),
        ("ON_HOLD", "On hold"),
        ("CANCELLED", "Cancelled"),
        ("REJECTED", "Rejected"),
        ("REVERSED", "Reversed"),
        ("RETURNED", "Returned"),
    )
    #: Canonical payment lifecycle. This is the single authoritative payment
    #: state for an episode -- it replaced the former payment_gate_state /
    #: payment_status pair, which could diverge. Do not add a second field that
    #: also expresses settlement; check_pos_dispensing_integrity fails the build
    #: if one reappears.
    PAYMENT_STATES = (
        ("NOT_REQUIRED", "Not required"),
        ("PENDING", "Pending"),
        ("AUTHORIZED", "Authorized"),
        ("PARTIALLY_PAID", "Partially paid"),
        ("PAID", "Paid"),
        ("WAIVED", "Waived"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
        ("REVERSAL_PENDING", "Reversal pending"),
        ("REVERSED", "Reversed"),
        ("REFUNDED", "Refunded"),
    )

    #: States in which medicine supply is commercially permitted. PARTIALLY_PAID
    #: is deliberately excluded: part-payment must not release stock.
    PAYMENT_STATES_PERMITTING_SUPPLY = frozenset(
        {"NOT_REQUIRED", "AUTHORIZED", "PAID", "WAIVED"}
    )

    #: States a caller may request when an episode is first created. Settlement
    #: states are absent by design -- an episode must never be born already paid.
    PAYMENT_STATES_AT_CREATION = frozenset({"NOT_REQUIRED", "PENDING", "WAIVED"})

    #: Permitted transitions. Terminal states have no outgoing edges.
    PAYMENT_TRANSITIONS = {
        "NOT_REQUIRED": {"PENDING", "CANCELLED"},
        "PENDING": {"AUTHORIZED", "PARTIALLY_PAID", "PAID", "WAIVED", "FAILED", "CANCELLED"},
        "AUTHORIZED": {"PARTIALLY_PAID", "PAID", "FAILED", "CANCELLED", "REVERSAL_PENDING"},
        "PARTIALLY_PAID": {"PARTIALLY_PAID", "PAID", "FAILED", "CANCELLED", "REVERSAL_PENDING"},
        "PAID": {"REVERSAL_PENDING", "REFUNDED"},
        "WAIVED": {"REVERSAL_PENDING"},
        "FAILED": {"PENDING", "CANCELLED"},
        "CANCELLED": set(),
        "REVERSAL_PENDING": {"REVERSED", "PAID"},
        "REVERSED": {"REFUNDED"},
        "REFUNDED": set(),
    }

    tenant_relation_fields = (
        "prescription",
        "patient",
        "branch",
        "pharmacy_location",
        "sales_order",
        "payment_register_session",
        "payment_operator_shift",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    dispensing_number = models.CharField(max_length=80)
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="dispensing_episodes",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="dispensing_episodes",
    )
    branch = models.ForeignKey(
        "organizations.Location",
        on_delete=models.PROTECT,
        related_name="+",
    )
    pharmacy_location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.PROTECT,
        related_name="+",
    )
    pharmacist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="DRAFT")
    initiated_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    supply_method = models.CharField(max_length=40, default="PATIENT_COLLECTION")
    sales_order = models.ForeignKey(
        "sales.SalesOrder",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dispensing_episodes",
    )
    payment_state = models.CharField(
        max_length=30,
        choices=PAYMENT_STATES,
        default="NOT_REQUIRED",
    )
    payment_idempotency_key = models.CharField(max_length=255, blank=True, default="")
    payment_reference = models.CharField(max_length=128, blank=True, default="")
    tender_type = models.CharField(max_length=64, default="CASH")
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    payment_register_session = models.ForeignKey(
        "pos_shift.RegisterSession",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_episodes",
    )
    payment_operator_shift = models.ForeignKey(
        "pos_shift.OperatorShift",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_episodes",
    )
    payment_device_id = models.CharField(max_length=128, blank=True, default="")
    collector_name = models.CharField(max_length=255, blank=True, default="")
    collector_id_number = models.CharField(max_length=128, blank=True, default="")
    collector_phone = models.CharField(max_length=64, blank=True, default="")
    collector_relationship = models.CharField(max_length=128, blank=True, default="")
    collection_proof_type = models.CharField(max_length=64, blank=True, default="")
    collected_at = models.DateTimeField(null=True, blank=True)
    controlled_witness = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    controlled_authority_checked = models.BooleanField(default=False)
    counselling_status = models.CharField(max_length=30, default="NOT_STARTED")
    notes = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "dispensing_number"],
                name="uq_dispensing_number",
            ),
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uq_dispensing_episode_key",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "branch", "status"],
                name="ix_dispensing_work_queue",
            )
        ]


class DispensingReservation(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = (
        "episode",
        "prescription_item",
        "inventory_reservation",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    episode = models.ForeignKey(
        DispensingEpisode,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.PROTECT,
        related_name="dispensing_reservations",
    )
    inventory_reservation = models.OneToOneField(
        "inventory.InventoryReservation",
        on_delete=models.PROTECT,
        related_name="dispensing_reservation",
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    status = models.CharField(max_length=30, default="ALLOCATED")
    idempotency_key = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uq_dispensing_reservation_key",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="chk_disp_reservation_qty",
            ),
        ]


class DispensingAllocation(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = (
        "episode",
        "prescription_item",
        "reservation",
        "inventory_batch",
        "location",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    episode = models.ForeignKey(
        DispensingEpisode,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.PROTECT,
        related_name="dispensing_allocations",
    )
    reservation = models.ForeignKey(
        DispensingReservation,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    inventory_batch = models.ForeignKey(
        "inventory.InventoryBatch",
        on_delete=models.PROTECT,
        related_name="+",
    )
    location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.PROTECT,
        related_name="+",
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    status = models.CharField(max_length=30, default="ALLOCATED")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reservation", "inventory_batch", "location"],
                name="uq_dispensing_allocation",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="chk_disp_allocation_qty",
            ),
        ]


class DispensingLine(TenantConsistencyMixin, TimestampedModel):
    STATUS_CHOICES = (
        ("AUTHORIZED", "Authorized"),
        ("PREPARED", "Prepared"),
        ("CHECKED", "Checked"),
        ("PARTIALLY_SUPPLIED", "Partially supplied"),
        ("SUPPLIED", "Supplied"),
        ("REVERSED", "Reversed"),
    )

    tenant_relation_fields = (
        "episode",
        "prescription_item",
        "prescribed_sku",
        "supplied_sku",
        "inventory_batch",
        "inventory_allocation",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    episode = models.ForeignKey(
        DispensingEpisode,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.PROTECT,
        related_name="dispensing_lines",
    )
    prescribed_sku = models.ForeignKey(
        "medicines.CommercialSKU",
        on_delete=models.PROTECT,
        related_name="+",
    )
    supplied_sku = models.ForeignKey(
        "medicines.CommercialSKU",
        on_delete=models.PROTECT,
        related_name="+",
    )
    inventory_batch = models.ForeignKey(
        "inventory.InventoryBatch",
        on_delete=models.PROTECT,
        related_name="+",
    )
    inventory_allocation = models.OneToOneField(
        DispensingAllocation,
        on_delete=models.PROTECT,
        related_name="dispensing_line",
    )
    quantity_authorized = models.DecimalField(max_digits=15, decimal_places=4)
    quantity_prepared = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    quantity_supplied = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    unit = models.CharField(max_length=50)
    package_definition = models.ForeignKey(
        "medicines.PackageDefinition",
        on_delete=models.PROTECT,
        related_name="+",
    )
    batch_number_snapshot = models.CharField(max_length=120)
    expiry_date_snapshot = models.DateField()
    dosage_label_instructions = models.TextField()
    substitution = models.ForeignKey(
        ClinicalSubstitution,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="AUTHORIZED")
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    checker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["episode", "inventory_allocation"],
                name="uq_dispensing_line_allocation",
            ),
            models.CheckConstraint(
                condition=Q(quantity_authorized__gt=0),
                name="chk_disp_line_authorized",
            ),
            models.CheckConstraint(
                condition=Q(quantity_prepared__gte=0),
                name="chk_disp_line_prepared_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(quantity_supplied__gte=0),
                name="chk_disp_line_supplied_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(quantity_prepared__lte=F("quantity_authorized")),
                name="chk_disp_line_prepared_limit",
            ),
            models.CheckConstraint(
                condition=Q(quantity_supplied__lte=F("quantity_prepared")),
                name="chk_disp_line_supply_limit",
            ),
        ]


class DispensingCheck(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("episode",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    episode = models.OneToOneField(
        DispensingEpisode,
        on_delete=models.PROTECT,
        related_name="final_check",
    )
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    checklist = models.JSONField(default=dict)
    outcome = models.CharField(max_length=30, default="PASSED")
    notes = models.TextField(blank=True, default="")
    checked_at = models.DateTimeField(default=timezone.now)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class DispensingLabel(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("episode", "dispensing_line", "stored_document")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    episode = models.ForeignKey(
        DispensingEpisode,
        on_delete=models.PROTECT,
        related_name="labels",
    )
    dispensing_line = models.ForeignKey(
        DispensingLine,
        on_delete=models.PROTECT,
        related_name="labels",
    )
    document_number = models.CharField(max_length=100)
    revision = models.PositiveIntegerField(default=1)
    label_size = models.CharField(max_length=40, default="PHARMACY_STANDARD")
    content = models.JSONField(default=dict)
    document_hash = models.CharField(max_length=64)
    barcode_payload = models.CharField(max_length=255)
    stored_document = models.ForeignKey(
        "documents.StoredClinicalDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    generated_at = models.DateTimeField(default=timezone.now)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dispensing_line", "revision"],
                name="uq_dispensing_label_revision",
            )
        ]


class PatientCounselling(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("episode", "patient")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    episode = models.OneToOneField(
        DispensingEpisode,
        on_delete=models.PROTECT,
        related_name="counselling",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="counselling_records",
    )
    counselling_required = models.BooleanField(default=False)
    counselling_completed = models.BooleanField(default=False)
    topics = models.JSONField(default=list, blank=True)
    warnings_explained = models.TextField(blank=True, default="")
    administration_instructions = models.TextField(blank=True, default="")
    storage_guidance = models.TextField(blank=True, default="")
    adherence_advice = models.TextField(blank=True, default="")
    side_effect_guidance = models.TextField(blank=True, default="")
    missed_dose_guidance = models.TextField(blank=True, default="")
    device_demonstration = models.BooleanField(default=False)
    patient_questions = models.TextField(blank=True, default="")
    language = models.CharField(max_length=40, blank=True, default="")
    interpreter = models.CharField(max_length=160, blank=True, default="")
    counselled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    counselled_at = models.DateTimeField(null=True, blank=True)
    refusal_reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()


class MedicineSupply(TenantConsistencyMixin, TimestampedModel):
    STATUS_CHOICES = (
        ("PARTIAL", "Partial"),
        ("COMPLETE", "Complete"),
        ("PARTIALLY_REVERSED", "Partially reversed"),
        ("REVERSED", "Reversed"),
    )

    tenant_relation_fields = ("episode", "prescription", "patient")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    supply_number = models.CharField(max_length=100)
    episode = models.ForeignKey(
        DispensingEpisode,
        on_delete=models.PROTECT,
        related_name="supplies",
    )
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="supplies",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="medicine_supplies",
    )
    supplied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    supplied_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    idempotency_key = models.CharField(max_length=255)
    correlation_id = models.CharField(max_length=160, blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "supply_number"],
                name="uq_medicine_supply_number",
            ),
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uq_medicine_supply_key",
            ),
        ]


class MedicineSupplyLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = (
        "supply",
        "dispensing_line",
        "prescription_item",
        "supplied_sku",
        "inventory_batch",
        "inventory_issue",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    supply = models.ForeignKey(
        MedicineSupply,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    dispensing_line = models.ForeignKey(
        DispensingLine,
        on_delete=models.PROTECT,
        related_name="supply_lines",
    )
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.PROTECT,
        related_name="supply_lines",
    )
    supplied_sku = models.ForeignKey(
        "medicines.CommercialSKU",
        on_delete=models.PROTECT,
        related_name="+",
    )
    inventory_batch = models.ForeignKey(
        "inventory.InventoryBatch",
        on_delete=models.PROTECT,
        related_name="+",
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit = models.CharField(max_length=50)
    outstanding_quantity = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        default=0,
    )
    partial_reason = models.CharField(max_length=60, blank=True, default="")
    next_eligible_date = models.DateField(null=True, blank=True)
    inventory_issue = models.OneToOneField(
        "inventory.InventoryLedgerEntry",
        on_delete=models.PROTECT,
        related_name="medicine_supply_line",
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["supply", "dispensing_line"],
                name="uq_supply_dispensing_line",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="chk_supply_line_qty",
            ),
            models.CheckConstraint(
                condition=Q(outstanding_quantity__gte=0),
                name="chk_supply_line_outstanding",
            ),
        ]


class PatientMedicationHistory(TenantConsistencyMixin, TimestampedModel):
    STATUS_CHOICES = (
        ("ACTIVE", "Active"),
        ("COMPLETED", "Completed"),
        ("REVERSED", "Reversed"),
        ("RETURNED", "Returned"),
    )

    tenant_relation_fields = (
        "patient",
        "prescription",
        "prescription_item",
        "dispensing_episode",
        "medicine_supply_line",
        "supplied_sku",
        "inventory_batch",
        "reversal_reference",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="medication_history",
    )
    prescription = models.ForeignKey(Prescription, on_delete=models.PROTECT, related_name="+")
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.PROTECT,
        related_name="+",
    )
    dispensing_episode = models.ForeignKey(
        DispensingEpisode,
        on_delete=models.PROTECT,
        related_name="+",
    )
    medicine_supply_line = models.ForeignKey(
        MedicineSupplyLine,
        on_delete=models.PROTECT,
        related_name="medication_history_entries",
    )
    medicine_name_snapshot = models.CharField(max_length=255)
    supplied_sku = models.ForeignKey(
        "medicines.CommercialSKU",
        on_delete=models.PROTECT,
        related_name="+",
    )
    active_ingredient_snapshot = models.JSONField(default=list, blank=True)
    strength_snapshot = models.CharField(max_length=120, blank=True, default="")
    dosage_form_snapshot = models.CharField(max_length=120, blank=True, default="")
    inventory_batch = models.ForeignKey(
        "inventory.InventoryBatch",
        on_delete=models.PROTECT,
        related_name="+",
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    instructions = models.TextField()
    supplied_at = models.DateTimeField()
    intended_start_date = models.DateField(null=True, blank=True)
    intended_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")
    source = models.CharField(max_length=80, default="MEDICINE_SUPPLY")
    reversal_reference = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["medicine_supply_line", "source"],
                name="uq_medication_history_source",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="chk_medication_history_qty",
            ),
        ]

    def save(self, *args, **kwargs):
        if (
            self.pk
            and PatientMedicationHistory.all_objects.filter(
                tenant_id=self.tenant_id,
                pk=self.pk,
            ).exists()
        ):
            raise ValidationError("Patient medication history is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Patient medication history cannot be deleted.")


class DispensingReversal(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("supply", "original_supply_line")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    reversal_number = models.CharField(max_length=100)
    supply = models.ForeignKey(
        MedicineSupply,
        on_delete=models.PROTECT,
        related_name="reversals",
    )
    original_supply_line = models.ForeignKey(
        MedicineSupplyLine,
        on_delete=models.PROTECT,
        related_name="reversals",
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    reason = models.TextField()
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    physically_returned = models.BooleanField(default=False)
    return_condition = models.CharField(max_length=60, blank=True, default="")
    inventory_eligibility = models.CharField(max_length=60, default="QUARANTINE_REQUIRED")
    idempotency_key = models.CharField(max_length=255)
    reversed_at = models.DateTimeField(default=timezone.now)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "reversal_number"],
                name="uq_dispensing_reversal_no",
            ),
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uq_dispensing_reversal_key",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="chk_dispensing_reversal_qty",
            ),
        ]


class PatientReturn(TenantConsistencyMixin, TimestampedModel):
    CONDITION_CHOICES = (
        ("UNOPENED", "Unopened"),
        ("OPENED", "Opened"),
        ("DAMAGED", "Damaged"),
        ("TEMPERATURE_COMPROMISED", "Temperature compromised"),
        ("EXPIRED", "Expired"),
        ("RECALLED", "Recalled"),
        ("DISPENSING_ERROR", "Dispensing error"),
        ("PATIENT_NO_LONGER_REQUIRES", "Patient no longer requires"),
    )

    tenant_relation_fields = (
        "supply",
        "patient",
        "quarantine_location",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    return_number = models.CharField(max_length=100)
    supply = models.ForeignKey(
        MedicineSupply,
        on_delete=models.PROTECT,
        related_name="patient_returns",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="medicine_returns",
    )
    reason = models.TextField()
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    inspected_at = models.DateTimeField(null=True, blank=True)
    quarantine_location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.PROTECT,
        related_name="+",
    )
    quality_decision = models.CharField(max_length=60, default="PENDING_INSPECTION")
    destruction_path = models.CharField(max_length=255, blank=True, default="")
    refund_eligibility = models.CharField(max_length=60, default="PENDING")
    status = models.CharField(max_length=40, default="RECEIVED")
    idempotency_key = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "return_number"],
                name="uq_patient_return_number",
            ),
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uq_patient_return_key",
            ),
        ]


class PatientReturnLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = (
        "patient_return",
        "original_supply_line",
        "inventory_batch",
    )
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    patient_return = models.ForeignKey(
        PatientReturn,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    original_supply_line = models.ForeignKey(
        MedicineSupplyLine,
        on_delete=models.PROTECT,
        related_name="patient_return_lines",
    )
    inventory_batch = models.ForeignKey(
        "inventory.InventoryBatch",
        on_delete=models.PROTECT,
        related_name="+",
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    condition = models.CharField(max_length=40, choices=PatientReturn.CONDITION_CHOICES)
    notes = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["patient_return", "original_supply_line"],
                name="uq_patient_return_supply_line",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="chk_patient_return_qty",
            ),
        ]


class ClinicalWorkItem(TenantConsistencyMixin, TimestampedModel):
    QUEUE_TYPE_CHOICES = (
        ("PRESCRIPTION_INTAKE", "Prescription intake"),
        ("LEGAL_VALIDATION", "Legal validation"),
        ("CLINICAL_REVIEW", "Clinical review"),
        ("CRITICAL_DUR_FINDING", "Critical DUR finding"),
        ("PRESCRIBER_CLARIFICATION", "Prescriber clarification"),
        ("PATIENT_CLARIFICATION", "Patient clarification"),
        ("PHARMACIST_VERIFICATION", "Pharmacist verification"),
        ("READY_FOR_DISPENSING", "Ready for dispensing"),
        ("DISPENSING_PREPARATION", "Dispensing preparation"),
        ("FINAL_CHECK", "Final check"),
        ("READY_FOR_COUNSELLING", "Ready for counselling"),
        ("READY_FOR_SUPPLY", "Ready for supply"),
        ("PARTIAL_DISPENSING_FOLLOW_UP", "Partial dispensing follow-up"),
        ("REPEAT_DUE", "Repeat due"),
        ("EARLY_REPEAT_REVIEW", "Early repeat review"),
        ("CONTROLLED_MEDICINE_REVIEW", "Controlled-medicine review"),
        ("PATIENT_RETURN_INSPECTION", "Patient return inspection"),
        ("REVERSAL_APPROVAL", "Reversal approval"),
    )
    STATUS_CHOICES = (
        ("OPEN", "Open"),
        ("IN_PROGRESS", "In progress"),
        ("CLOSED", "Closed"),
        ("CANCELLED", "Cancelled"),
    )

    tenant_relation_fields = ("prescription", "dispensing_episode", "branch")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    queue_type = models.CharField(max_length=80, choices=QUEUE_TYPE_CHOICES)
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="work_items",
    )
    dispensing_episode = models.ForeignKey(
        DispensingEpisode,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="work_items",
    )
    branch = models.ForeignKey(
        "organizations.Location",
        on_delete=models.PROTECT,
        related_name="+",
    )
    required_capability = models.CharField(max_length=160)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="OPEN")
    due_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "queue_type", "prescription"],
                condition=Q(
                    dispensing_episode__isnull=True,
                    status__in=["OPEN", "IN_PROGRESS"],
                ),
                name="uq_active_rx_work_item",
            ),
            models.UniqueConstraint(
                fields=[
                    "tenant",
                    "queue_type",
                    "prescription",
                    "dispensing_episode",
                ],
                condition=Q(
                    dispensing_episode__isnull=False,
                    status__in=["OPEN", "IN_PROGRESS"],
                ),
                name="uq_active_episode_work_item",
            )
        ]
        indexes = [
            models.Index(
                fields=["tenant", "branch", "queue_type", "status"],
                name="ix_clinical_work_queue",
            )
        ]


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


class PosShiftRecord(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"
        RECONCILED = "RECONCILED", "Reconciled"

    tenant_relation_fields = ("location", "cashier", "pharmacist")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    shift_number = models.CharField(max_length=64)
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    pharmacist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    location = models.ForeignKey(
        "organizations.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    controlled_stock_start_count = models.IntegerField(default=0)
    controlled_stock_end_count = models.IntegerField(default=0)
    outstanding_episode_count = models.IntegerField(default=0)
    discrepancy_declared = models.BooleanField(default=False)
    declaration_notes = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "shift_number"], name="uq_pos_shift_number")
        ]

    def __str__(self):
        return f"Shift {self.shift_number} [{self.status}]"


class PosDeviceHealthRecord(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        OK = "OK", "OK"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"
        OFFLINE = "OFFLINE", "Offline"

    tenant_relation_fields = ()
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    device_id = models.CharField(max_length=128)
    device_type = models.CharField(max_length=64, default="TERMINAL")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OK)
    printer_paper_level = models.CharField(max_length=32, default="OK")
    scanner_connected = models.BooleanField(default=True)
    cash_drawer_open = models.BooleanField(default=False)
    network_latency_ms = models.IntegerField(default=0)
    battery_level_pct = models.IntegerField(null=True, blank=True)
    storage_used_pct = models.IntegerField(default=0)
    telemetry_data = models.JSONField(default=dict, blank=True)
    last_heartbeat = models.DateTimeField(default=timezone.now)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "device_id"], name="uq_pos_device_health_id")
        ]

    def __str__(self):
        return f"Device {self.device_id} [{self.status}]"


class PosLabelReprintAudit(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("label", "reprinted_by")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    label = models.ForeignKey(DispensingLabel, on_delete=models.CASCADE, related_name="reprints")
    reprinted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    reprint_reason = models.CharField(max_length=255, blank=True, default="")
    reprinted_at = models.DateTimeField(default=timezone.now)
    #: Recorded at print time rather than inferred later. Whether a copy was the
    #: original is a fact about that moment; deriving it from a count afterwards
    #: breaks as soon as a failed attempt is inserted between prints.
    is_original = models.BooleanField(default=False)
    printer = models.CharField(max_length=128, blank=True, default="")
    #: Failed attempts are kept: a printer that jams three times and succeeds
    #: once produced one label, and the audit must show that.
    status = models.CharField(
        max_length=20,
        choices=(("SUCCEEDED", "Succeeded"), ("FAILED", "Failed")),
        default="SUCCEEDED",
    )
    failure_reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"Reprint for {self.label.document_number} by {self.reprinted_by_id}"


# The POS payment intent and settlement ledger lives in its own module for
# readability; re-exported here so Django registers it with this app.
from apps.prescription.payment_models import (  # noqa: E402,F401
    PaymentAttempt,
    PaymentIntent,
    PaymentProviderEvent,
    PaymentReversal,
    PaymentSettlement,
    PaymentTender,
)
from apps.prescription.pos_printing_models import PosPrintDocument, PosPrintJob  # noqa: E402,F401
