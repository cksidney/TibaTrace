import uuid

import apps.core.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_departments"),
        ("platform", "0004_demo_story_metadata"),
        ("pos_shift", "0003_cashexceptionreview"),
        ("tenancy", "0003_tenant_is_demo"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="PosActivationRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("device_id", models.CharField(max_length=120)),
                ("device_fingerprint", models.CharField(max_length=255)),
                ("device_name", models.CharField(max_length=160)),
                ("device_type", models.CharField(max_length=32)),
                ("app_version", models.CharField(blank=True, max_length=40)),
                ("justification", models.TextField()),
                ("state", models.CharField(db_index=True, default="SUBMITTED", max_length=24)),
                ("rationale", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("challenge_hash", models.CharField(blank=True, max_length=64)),
                ("challenge_expires_at", models.DateTimeField(blank=True, null=True)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("activation_expires_at", models.DateTimeField(blank=True, null=True)),
                ("credential_hash", models.CharField(blank=True, max_length=64)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="organizations.location")),
                ("register", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="pos_shift.posregister")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pos_activation_requests", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pos_activation_reviews", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.tenant")),
            ],
            options={"constraints": [models.UniqueConstraint(condition=models.Q(state__in=["SUBMITTED", "APPROVED", "ACTIVATED"]), fields=("tenant", "device_id"), name="uq_pos_active_device_request")]},
            bases=(apps.core.models.TenantConsistencyMixin, models.Model),
        ),
    ]
