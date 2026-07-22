from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel


class Medicine(TimestampedModel):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_INACTIVE = "INACTIVE"
    STATUS_DISCONTINUED = "DISCONTINUED"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_DISCONTINUED, "Discontinued"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="medicines")
    is_global = models.BooleanField(default=False)
    code = models.CharField(max_length=120)
    generic_name = models.CharField(max_length=255)
    brand_name = models.CharField(max_length=255, blank=True)
    dosage_form = models.CharField(max_length=120, blank=True)
    strength = models.CharField(max_length=120, blank=True)
    gtin = models.CharField(max_length=32, blank=True)
    primary_barcode = models.CharField(max_length=80, blank=True)
    atc_code = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    source = models.CharField(max_length=160)
    source_version = models.CharField(max_length=80)
    licence_identifier = models.CharField(max_length=160, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(tenant__isnull=True, is_global=True)
                    | models.Q(tenant__isnull=False, is_global=False)
                ),
                name="ck_medicine_explicit_scope",
            ),
            models.UniqueConstraint(
                fields=["tenant", "code"],
                condition=models.Q(tenant__isnull=False),
                name="uq_medicine_tenant_code",
            ),
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(tenant__isnull=True, is_global=True),
                name="uq_medicine_global_code",
            ),
        ]

    def clean(self):
        super().clean()
        if self.is_global == bool(self.tenant_id):
            raise ValidationError("Medicine scope must be one tenant or explicitly global.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class MedicineIdentifier(TimestampedModel):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name="identifiers")
    system = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["system", "value"], name="uq_medicine_identifier")]
