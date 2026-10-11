import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("medicines", "0003_tenantcatalogueproduct"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LegacyCatalogueImport",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.CharField(max_length=120)),
                ("source_date", models.DateField()),
                ("provenance", models.JSONField(default=dict)),
                ("imported_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.tenant")),
            ],
            options={"constraints":[models.UniqueConstraint(fields=("tenant", "code"), name="uq_legacy_catalogue_import")]},
        ),
        migrations.CreateModel(
            name="LegacyCatalogueItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("source_key", models.CharField(max_length=120)),
                ("source_row", models.PositiveIntegerField()),
                ("legacy_code", models.CharField(blank=True, max_length=120)),
                ("proposed_sku_code", models.CharField(max_length=120)),
                ("source_name", models.CharField(max_length=255)),
                ("source_uom", models.CharField(blank=True, max_length=80)),
                ("source_cost", models.DecimalField(decimal_places=4, max_digits=18)),
                ("source_price", models.DecimalField(decimal_places=4, max_digits=18)),
                ("source_quantity", models.DecimalField(decimal_places=4, max_digits=18)),
                ("source_product", models.JSONField(default=dict)),
                ("source_stock", models.JSONField(default=dict)),
                ("source_issues", models.JSONField(blank=True, default=list)),
                ("review", models.JSONField(blank=True, default=dict)),
                ("import_batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="medicines.legacycatalogueimport")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.tenant")),
            ],
            options={
                "constraints":[models.UniqueConstraint(fields=("tenant", "import_batch", "source_key"), name="uq_legacy_catalogue_item")],
                "indexes":[models.Index(fields=["tenant", "import_batch", "source_row"], name="ix_legacy_catalogue_review")],
            },
        ),
    ]
