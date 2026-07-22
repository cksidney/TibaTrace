from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class StoredClinicalDocument(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("patient",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="stored_documents")
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True, related_name="stored_documents"
    )
    object_key = models.CharField(max_length=512)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120)
    size_bytes = models.PositiveBigIntegerField()
    hash_sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    malware_scan_status = models.CharField(max_length=30, default="PENDING")
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "object_key"], name="uq_document_object_key_tenant")
        ]
        indexes = [models.Index(fields=["tenant", "patient", "created_at"], name="ix_document_patient")]

    def clean(self):
        super().clean()
        prefix = f"tenant/{self.tenant_id}/"
        if self.tenant_id and not self.object_key.startswith(prefix):
            raise ValidationError({"object_key": "Object key must be tenant scoped."})
        if len(self.hash_sha256) != 64:
            raise ValidationError({"hash_sha256": "A SHA-256 digest is required."})


class DocumentAccessEvent(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="document_access_events")
    document = models.ForeignKey(StoredClinicalDocument, on_delete=models.PROTECT, related_name="access_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=40)
    outcome = models.CharField(max_length=40)
    reason = models.CharField(max_length=255, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def save(self, *args, **kwargs):
        # tenant-safety: immutable-existence-check
        if self.pk and DocumentAccessEvent.all_objects.filter(pk=self.pk).exists():
            raise ValidationError("Document access events are immutable.")
        return super().save(*args, **kwargs)
