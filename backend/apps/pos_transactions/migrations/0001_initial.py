import apps.core.models
import apps.pos_transactions.models
import django.db.models.deletion
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("customers", "0003_alter_customer_customer_type"),
        ("inventory", "0004_replenishmentrecommendation_warehousetask_and_more"),
        ("medicines", "0003_tenantcatalogueproduct"),
        ("organizations", "0001_initial"),
        ("patients", "0002_patientclinicalsummary_patientconditionsummary_and_more"),
        ("pos_shift", "0002_shiftreport_shiftreportreprint_and_more"),
        ("tenancy", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PosTransaction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("transaction_number", models.CharField(default=apps.pos_transactions.models.transaction_number, max_length=32)),
                ("device_id", models.CharField(max_length=128)),
                ("state", models.CharField(choices=[("DRAFT", "Draft"), ("HELD", "Held"), ("READY_FOR_PAYMENT", "Ready for payment"), ("PAYMENT_IN_PROGRESS", "Payment in progress"), ("PAID", "Paid"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled"), ("VOIDED", "Voided")], db_index=True, default="DRAFT", max_length=24)),
                ("channel", models.CharField(choices=[("RETAIL", "Retail")], default="RETAIL", max_length=20)),
                ("currency", models.CharField(default="KES", max_length=3)),
                ("subtotal", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=15)),
                ("discount_total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=15)),
                ("tax_total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=15)),
                ("total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=15)),
                ("hold_reason", models.TextField(blank=True, default="")),
                ("held_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("cancellation_reason", models.TextField(blank=True, default="")),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pos_transactions", to="organizations.location")),
                ("business_day", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transactions", to="pos_shift.businessday")),
                ("customer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pos_transactions", to="customers.customer")),
                ("operator", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pos_transactions", to=settings.AUTH_USER_MODEL)),
                ("operator_shift", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transactions", to="pos_shift.operatorshift")),
                ("patient", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pos_transactions", to="patients.patient")),
                ("register", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transactions", to="pos_shift.posregister")),
                ("register_session", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transactions", to="pos_shift.registersession")),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pos_transactions", to="inventory.inventorylocation")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pos_transactions", to="tenancy.tenant")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["tenant", "state"], name="ix_pos_transaction_state"),
                    models.Index(fields=["tenant", "register_session"], name="ix_pos_transaction_session"),
                ],
            },
            bases=(apps.core.models.TenantConsistencyMixin, models.Model),
        ),
        migrations.CreateModel(
            name="PosTransactionLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("description_snapshot", models.CharField(max_length=500)),
                ("unit", models.CharField(max_length=50)),
                ("quantity", models.DecimalField(decimal_places=4, max_digits=15)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=15)),
                ("discount_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=15)),
                ("tax_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=15)),
                ("line_total", models.DecimalField(decimal_places=2, max_digits=15)),
                ("currency", models.CharField(default="KES", max_length=3)),
                ("price_snapshot", models.JSONField(default=dict)),
                ("scan_source", models.CharField(default="SEARCH", max_length=20)),
                ("sku", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pos_transaction_lines", to="medicines.commercialsku")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pos_transaction_lines", to="tenancy.tenant")),
                ("transaction", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="pos_transactions.postransaction")),
            ],
            bases=(apps.core.models.TenantConsistencyMixin, models.Model),
        ),
        migrations.CreateModel(
            name="PosTransactionInventoryContext",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("available_quantity", models.DecimalField(decimal_places=4, default=Decimal("0.0000"), max_digits=15)),
                ("stock_state", models.CharField(choices=[("IN_STOCK", "In stock"), ("OUT_OF_STOCK", "Out of stock"), ("INSUFFICIENT", "Insufficient stock"), ("NOT_TRACKED", "Stock not tracked")], max_length=20)),
                ("policy", models.JSONField(default=dict)),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pos_inventory_contexts", to="inventory.inventorylocation")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pos_inventory_contexts", to="tenancy.tenant")),
                ("transaction_line", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_context", to="pos_transactions.postransactionline")),
            ],
            bases=(apps.core.models.TenantConsistencyMixin, models.Model),
        ),
        migrations.AddConstraint(model_name="postransaction", constraint=models.UniqueConstraint(fields=("tenant", "transaction_number"), name="uq_pos_transaction_tenant_number")),
        migrations.AddConstraint(model_name="postransaction", constraint=models.CheckConstraint(condition=models.Q(("subtotal__gte", 0)), name="chk_pos_transaction_subtotal_nonneg")),
        migrations.AddConstraint(model_name="postransaction", constraint=models.CheckConstraint(condition=models.Q(("discount_total__gte", 0)), name="chk_pos_transaction_discount_nonneg")),
        migrations.AddConstraint(model_name="postransaction", constraint=models.CheckConstraint(condition=models.Q(("tax_total__gte", 0)), name="chk_pos_transaction_tax_nonneg")),
        migrations.AddConstraint(model_name="postransaction", constraint=models.CheckConstraint(condition=models.Q(("total__gte", 0)), name="chk_pos_transaction_total_nonneg")),
        migrations.AddConstraint(model_name="postransactionline", constraint=models.UniqueConstraint(fields=("transaction", "sku"), name="uq_pos_transaction_line_sku")),
        migrations.AddConstraint(model_name="postransactionline", constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="chk_pos_transaction_line_qty_positive")),
        migrations.AddConstraint(model_name="postransactionline", constraint=models.CheckConstraint(condition=models.Q(("unit_price__gte", 0)), name="chk_pos_transaction_line_price_nonneg")),
        migrations.AddConstraint(model_name="postransactionline", constraint=models.CheckConstraint(condition=models.Q(("line_total__gte", 0)), name="chk_pos_transaction_line_total_nonneg")),
    ]
