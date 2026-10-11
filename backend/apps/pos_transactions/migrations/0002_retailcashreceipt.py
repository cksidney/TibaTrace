import apps.core.models
import apps.pos_transactions.models
import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        ("pos_transactions", "0001_initial"),
        ("tenancy", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RetailCashReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("receipt_number", models.CharField(default=apps.pos_transactions.models.retail_receipt_number, max_length=32)),
                ("tender_type", models.CharField(choices=[("CASH", "Cash")], default="CASH", max_length=12)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=15)),
                ("cash_received", models.DecimalField(decimal_places=2, max_digits=15)),
                ("change_due", models.DecimalField(decimal_places=2, max_digits=15)),
                ("currency", models.CharField(default="KES", max_length=3)),
                ("lines_snapshot", models.JSONField(default=list)),
                ("totals_snapshot", models.JSONField(default=dict)),
                ("idempotency_key", models.CharField(max_length=255)),
                ("settled_at", models.DateTimeField(default=timezone.now)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="retail_cash_receipts", to="tenancy.tenant")),
                ("transaction", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cash_receipt", to="pos_transactions.postransaction")),
            ],
            bases=(apps.core.models.TenantConsistencyMixin, models.Model),
        ),
        migrations.AddConstraint(
            model_name="retailcashreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(tender_type="CASH"), name="chk_retail_cash_receipt_cash_only"
            ),
        ),
        migrations.AddConstraint(
            model_name="retailcashreceipt",
            constraint=models.UniqueConstraint(
                fields=("tenant", "receipt_number"), name="uq_retail_cash_receipt_number"
            ),
        ),
        migrations.AddConstraint(
            model_name="retailcashreceipt",
            constraint=models.UniqueConstraint(
                fields=("tenant", "idempotency_key"), name="uq_retail_cash_receipt_idempotency"
            ),
        ),
        migrations.AddConstraint(
            model_name="retailcashreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="chk_retail_cash_receipt_amount_positive"
            ),
        ),
        migrations.AddConstraint(
            model_name="retailcashreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(cash_received__gte=models.F("amount")),
                name="chk_retail_cash_receipt_tender_covers_total",
            ),
        ),
        migrations.AddConstraint(
            model_name="retailcashreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(change_due__gte=0), name="chk_retail_cash_receipt_change_nonneg"
            ),
        ),
        migrations.AddConstraint(
            model_name="retailcashreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(change_due=models.F("cash_received") - models.F("amount")),
                name="chk_retail_cash_receipt_change_matches",
            ),
        ),
    ]
