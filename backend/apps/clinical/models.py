from __future__ import annotations

from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class ClinicalEncounter(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("patient", "organization", "location", "practitioner")
    STATUS_CHOICES = (
        ("PLANNED", "Planned"),
        ("ARRIVED", "Arrived"),
        ("TRIAGED", "Triaged"),
        ("IN_PROGRESS", "In progress"),
        ("ONLEAVE", "On leave"),
        ("FINISHED", "Finished"),
        ("CANCELLED", "Cancelled"),
        ("ENTERED_IN_ERROR", "Entered in error"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="clinical_encounters")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="encounters")
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="IN_PROGRESS")
    encounter_class = models.CharField(max_length=50)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="encounters"
    )
    location = models.ForeignKey(
        "organizations.Location", on_delete=models.PROTECT, null=True, blank=True, related_name="encounters"
    )
    practitioner = models.ForeignKey(
        "practitioners.Practitioner", on_delete=models.PROTECT, null=True, blank=True, related_name="encounters"
    )
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    reason_code = models.CharField(max_length=100, null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "patient", "status"], name="ix_clinical_enc_patient")]


class ClinicalCondition(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("patient", "encounter")
    STATUS_CHOICES = (
        ("ACTIVE", "Active"),
        ("RECURRENCE", "Recurrence"),
        ("RELAPSE", "Relapse"),
        ("INACTIVE", "Inactive"),
        ("REMISSION", "Remission"),
        ("RESOLVED", "Resolved"),
    )
    VERIFICATION_CHOICES = (
        ("UNCONFIRMED", "Unconfirmed"),
        ("PROVISIONAL", "Provisional"),
        ("DIFFERENTIAL", "Differential"),
        ("CONFIRMED", "Confirmed"),
        ("REFUTED", "Refuted"),
        ("ENTERED_IN_ERROR", "Entered in error"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="clinical_conditions")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="conditions")
    encounter = models.ForeignKey(ClinicalEncounter, on_delete=models.SET_NULL, null=True, blank=True)
    clinical_status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="ACTIVE")
    verification_status = models.CharField(max_length=50, choices=VERIFICATION_CHOICES, default="UNCONFIRMED")
    category = models.CharField(max_length=100, null=True, blank=True)
    code = models.CharField(max_length=100)
    system = models.CharField(max_length=255, null=True, blank=True)
    display = models.CharField(max_length=255, null=True, blank=True)
    onset_date = models.DateTimeField(null=True, blank=True)
    recorded_date = models.DateTimeField(auto_now_add=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "patient", "clinical_status"], name="ix_clinical_condition")]


class ClinicalObservation(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("patient", "encounter")
    STATUS_CHOICES = (
        ("REGISTERED", "Registered"),
        ("PRELIMINARY", "Preliminary"),
        ("FINAL", "Final"),
        ("AMENDED", "Amended"),
        ("CORRECTED", "Corrected"),
        ("CANCELLED", "Cancelled"),
        ("ENTERED_IN_ERROR", "Entered in error"),
        ("UNKNOWN", "Unknown"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="clinical_observations")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="observations")
    encounter = models.ForeignKey(ClinicalEncounter, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="FINAL")
    category = models.CharField(max_length=100, null=True, blank=True)
    code = models.CharField(max_length=100)
    system = models.CharField(max_length=255, null=True, blank=True)
    display = models.CharField(max_length=255, null=True, blank=True)
    effective_time = models.DateTimeField(null=True, blank=True)
    value_quantity = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    value_unit = models.CharField(max_length=50, null=True, blank=True)
    value_string = models.CharField(max_length=255, null=True, blank=True)
    interpretation = models.CharField(max_length=50, null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "patient", "status"], name="ix_clinical_observation")]


class ClinicalDiagnosticReport(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("patient", "encounter")
    STATUS_CHOICES = (
        ("REGISTERED", "Registered"),
        ("PARTIAL", "Partial"),
        ("PRELIMINARY", "Preliminary"),
        ("FINAL", "Final"),
        ("AMENDED", "Amended"),
        ("CORRECTED", "Corrected"),
        ("APPENDED", "Appended"),
        ("CANCELLED", "Cancelled"),
        ("ENTERED_IN_ERROR", "Entered in error"),
        ("UNKNOWN", "Unknown"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="diagnostic_reports")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="diagnostic_reports")
    encounter = models.ForeignKey(ClinicalEncounter, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="FINAL")
    category = models.CharField(max_length=100, null=True, blank=True)
    code = models.CharField(max_length=100)
    system = models.CharField(max_length=255, null=True, blank=True)
    display = models.CharField(max_length=255, null=True, blank=True)
    effective_time = models.DateTimeField(null=True, blank=True)
    conclusion = models.TextField(null=True, blank=True)
    observations = models.ManyToManyField(ClinicalObservation, related_name="diagnostic_reports", blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "patient", "status"], name="ix_clinical_report")]


class ClinicalDocument(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("patient", "encounter", "author")
    STATUS_CHOICES = (
        ("CURRENT", "Current"),
        ("SUPERSEDED", "Superseded"),
        ("ENTERED_IN_ERROR", "Entered in error"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="clinical_documents")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="clinical_documents")
    encounter = models.ForeignKey(ClinicalEncounter, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="CURRENT")
    doc_type = models.CharField(max_length=100, null=True, blank=True)
    category = models.CharField(max_length=100, null=True, blank=True)
    object_url = models.CharField(max_length=512)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    hash_sha256 = models.CharField(max_length=64, null=True, blank=True)
    author = models.ForeignKey(
        "practitioners.Practitioner", on_delete=models.SET_NULL, null=True, blank=True, related_name="clinical_documents"
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "patient", "status"], name="ix_clinical_document")]


class MedicationAdministrationRecord(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("patient", "encounter", "prescription_item", "performer")
    STATUS_CHOICES = (
        ("IN_PROGRESS", "In progress"),
        ("NOT_DONE", "Not done"),
        ("ON_HOLD", "On hold"),
        ("COMPLETED", "Completed"),
        ("ENTERED_IN_ERROR", "Entered in error"),
        ("STOPPED", "Stopped"),
        ("UNKNOWN", "Unknown"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="medication_administrations")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="medication_administrations")
    encounter = models.ForeignKey(ClinicalEncounter, on_delete=models.SET_NULL, null=True, blank=True)
    prescription_item = models.ForeignKey(
        "prescription.PrescriptionItem", on_delete=models.SET_NULL, null=True, blank=True
    )
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="COMPLETED")
    medication_name = models.CharField(max_length=255)
    effective_time = models.DateTimeField(null=True, blank=True)
    dosage_text = models.TextField(null=True, blank=True)
    performer = models.ForeignKey(
        "practitioners.Practitioner", on_delete=models.SET_NULL, null=True, blank=True
    )
    reason_not_done = models.CharField(max_length=255, null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "patient", "status"], name="ix_clinical_med_admin")]
