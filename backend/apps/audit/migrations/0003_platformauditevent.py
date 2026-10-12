import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformAuditEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("action", models.CharField(max_length=120)),
                ("model_name", models.CharField(max_length=120)),
                ("object_id", models.CharField(max_length=160)),
                ("correlation_id", models.CharField(blank=True, max_length=160)),
                ("outcome", models.CharField(default="SUCCESS", max_length=40)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="platform_audit_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["model_name", "object_id"], name="ix_platform_audit_object"),
                    models.Index(fields=["created_at"], name="ix_platform_audit_created"),
                ],
            },
        ),
    ]
