"""Legacy source records, not medicines, SKUs, prices or stock ledger entries."""
from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel


class LegacyCatalogueImport(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT)
    code = models.CharField(max_length=120)
    source_date = models.DateField()
    provenance = models.JSONField(default=dict)
    imported_by = models.ForeignKey("identity.User", on_delete=models.PROTECT)
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_legacy_catalogue_import")]


class LegacyCatalogueItem(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT)
    import_batch = models.ForeignKey(LegacyCatalogueImport, on_delete=models.PROTECT, related_name="items")
    source_key = models.CharField(max_length=120)
    source_row = models.PositiveIntegerField()
    legacy_code = models.CharField(max_length=120, blank=True)
    proposed_sku_code = models.CharField(max_length=120)
    source_name = models.CharField(max_length=255)
    source_uom = models.CharField(max_length=80, blank=True)
    source_cost = models.DecimalField(max_digits=18, decimal_places=4)
    source_price = models.DecimalField(max_digits=18, decimal_places=4)
    source_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    source_product = models.JSONField(default=dict)
    source_stock = models.JSONField(default=dict)
    source_issues = models.JSONField(default=list, blank=True)
    # Only these manager inputs are editable. Source columns stay unchanged.
    review = models.JSONField(default=dict, blank=True)
    # Governed downstream lineage is separate from editable Manager evidence.
    completion = models.JSONField(default=dict, blank=True)
    reviewed_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, null=True, blank=True)
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "import_batch", "source_key"], name="uq_legacy_catalogue_item")]
        indexes = [models.Index(fields=["tenant", "import_batch", "source_row"], name="ix_legacy_catalogue_review")]
