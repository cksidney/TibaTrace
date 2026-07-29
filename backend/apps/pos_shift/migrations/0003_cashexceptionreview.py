import apps.core.models
import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pos_shift", "0002_shiftreport_shiftreportreprint_and_more"),
        ("tenancy", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CashExceptionReview",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("UNDER_REVIEW", "Under review"),
                            ("RESOLVED", "Resolved"),
                        ],
                        default="UNDER_REVIEW",
                        max_length=20,
                    ),
                ),
                ("opened_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("opening_note", models.TextField()),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_note", models.TextField(blank=True, default="")),
                (
                    "opened_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "report",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cash_exception_review",
                        to="pos_shift.shiftreport",
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cash_exception_reviews",
                        to="tenancy.tenant",
                    ),
                ),
            ],
            options={"ordering": ["-opened_at"]},
            bases=(apps.core.models.TenantConsistencyMixin, models.Model),
        ),
    ]
