"""Immutable POS documents and durable print jobs.

Documents are historical facts rendered from authoritative settlement or
dispensing state. Print jobs are intentionally separate: printer transport
failure must never alter settlement, inventory, or the document snapshot.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class PosPrintDocument(TenantConsistencyMixin, TimestampedModel):
    class DocumentType(models.TextChoices):
        RETAIL_RECEIPT = "RETAIL_RECEIPT", "Retail receipt"
        PRESCRIPTION_RECEIPT = "PRESCRIPTION_RECEIPT", "Prescription receipt"
        MEDICINE_LABEL = "MEDICINE_LABEL", "Medicine label"
        CASH_MOVEMENT_RECEIPT = "CASH_MOVEMENT_RECEIPT", "Cash movement receipt"
        X_REPORT = "X_REPORT", "X report"
        Z_REPORT = "Z_REPORT", "Z report"
        REVERSAL_RECEIPT = "REVERSAL_RECEIPT", "Reversal receipt"
        INSURANCE_SUPPORTING_DOCUMENT = "INSURANCE_SUPPORTING_DOCUMENT", "Insurance supporting document"

    tenant_relation_fields = ("episode", "settlement", "label", "register_session")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    document_type = models.CharField(max_length=48, choices=DocumentType.choices)
    document_number = models.CharField(max_length=128)
    snapshot = models.JSONField(default=dict)
    document_hash = models.CharField(max_length=64)
    episode = models.ForeignKey(
        "prescription.DispensingEpisode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="print_documents",
    )
    settlement = models.ForeignKey(
        "prescription.PaymentSettlement",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="print_documents",
    )
    label = models.ForeignKey(
        "prescription.DispensingLabel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="print_documents",
    )
    register_session = models.ForeignKey(
        "pos_shift.RegisterSession",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="print_documents",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidation_reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "document_number"],
                name="uq_pos_print_document_number",
            ),
            models.UniqueConstraint(
                fields=["settlement", "document_type"],
                condition=Q(settlement__isnull=False),
                name="uq_pos_print_document_settlement_type",
            ),
            models.UniqueConstraint(
                fields=["label", "document_type"],
                condition=Q(label__isnull=False),
                name="uq_pos_print_document_label_type",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "document_type"], name="ix_pos_print_doc_tenant_type"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and PosPrintDocument.all_objects.filter(
            tenant_id=self.tenant_id,
            pk=self.pk,
        ).exists():
            raise ValueError("PosPrintDocument is immutable; create a new document revision instead.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.document_type} {self.document_number}"


class PosPrintJob(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RENDERED = "RENDERED", "Rendered"
        SENDING = "SENDING", "Sending"
        PRINTED = "PRINTED", "Printed"
        FAILED = "FAILED", "Failed"
        RETRY_REQUIRED = "RETRY_REQUIRED", "Retry required"
        CANCELLED = "CANCELLED", "Cancelled"

    class Transport(models.TextChoices):
        WINDOWS_SPOOLER = "WINDOWS_SPOOLER", "Windows spooler"
        ESCPOS_USB = "ESCPOS_USB", "ESC/POS USB"
        ESCPOS_NETWORK = "ESCPOS_NETWORK", "ESC/POS network"
        ANDROID_BLUETOOTH = "ANDROID_BLUETOOTH", "Android Bluetooth"
        ANDROID_NETWORK = "ANDROID_NETWORK", "Android network"
        SIMULATOR = "SIMULATOR", "Deterministic simulator"
        PDF_FALLBACK = "PDF_FALLBACK", "PDF fallback"

    class CopyClassification(models.TextChoices):
        ORIGINAL = "ORIGINAL", "Original"
        REPRINT = "REPRINT", "Reprint"

    tenant_relation_fields = ("document", "branch", "requested_by", "printed_by", "cancelled_by")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    document = models.ForeignKey(PosPrintDocument, on_delete=models.PROTECT, related_name="jobs")
    branch = models.ForeignKey(
        "organizations.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    device_id = models.CharField(max_length=128, blank=True, default="")
    printer = models.CharField(max_length=128, blank=True, default="")
    transport = models.CharField(max_length=32, choices=Transport.choices, default=Transport.SIMULATOR)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.QUEUED)
    copy_classification = models.CharField(
        max_length=16,
        choices=CopyClassification.choices,
        default=CopyClassification.ORIGINAL,
    )
    copy_number = models.PositiveIntegerField(default=1)
    reprint_reason = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=64, blank=True, default="")
    failure_message = models.TextField(blank=True, default="")
    printed_at = models.DateTimeField(null=True, blank=True)
    printed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    cancellation_reason = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uq_pos_print_job_idempotency",
            ),
            models.UniqueConstraint(
                fields=["document", "copy_number"],
                name="uq_pos_print_job_document_copy",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="ix_pos_print_job_tenant_status"),
            models.Index(fields=["tenant", "printer"], name="ix_pos_prn_job_printer"),
            models.Index(fields=["tenant", "branch", "status"], name="ix_pos_print_job_branch"),
            models.Index(fields=["tenant", "device_id", "status"], name="ix_pos_prn_job_device"),
        ]

    def __str__(self):
        return f"{self.document.document_number} copy {self.copy_number} [{self.status}]"
