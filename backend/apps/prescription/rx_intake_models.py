from django.conf import settings
from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class PrescriptionIntakeReceipt(TenantConsistencyMixin, TimestampedModel):
    """Immutable origin and retry evidence, separate from mutable clinical review."""

    tenant_relation_fields = ("prescription", "branch", "actor")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT)
    prescription = models.OneToOneField("prescription.Prescription", on_delete=models.PROTECT, related_name="intake_receipt")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    device_id = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=180)
    source_key = models.CharField(max_length=180)
    payload_hash = models.CharField(max_length=64)
    provider_code = models.CharField(max_length=32, blank=True)
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uq_rx_intake_command"),
            models.UniqueConstraint(fields=["tenant", "source_key"], name="uq_rx_intake_source"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Prescription intake evidence is immutable.")
        return super().save(*args, **kwargs)


class PrescriptionSourceDocument(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("prescription", "document")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT)
    prescription = models.ForeignKey("prescription.Prescription", on_delete=models.PROTECT, related_name="source_documents")
    document = models.ForeignKey("documents.StoredClinicalDocument", on_delete=models.PROTECT)
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["prescription", "document"], name="uq_rx_source_document")]
