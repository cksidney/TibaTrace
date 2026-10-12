from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0004_financial_provider_templates"),
    ]

    operations = [
        migrations.AlterField(
            model_name="provideractivationrequest",
            name="state",
            field=models.CharField(
                choices=[
                    ("REQUESTED", "Requested"),
                    ("UNDER_REVIEW", "Under review"),
                    ("SECURITY_REVIEW", "Security review"),
                    ("SANDBOX_CONFIGURED", "Sandbox configured"),
                    ("SANDBOX_TESTING", "Sandbox testing"),
                    ("SANDBOX_PASSED", "Sandbox passed"),
                    ("CERTIFICATION_REVIEW", "Certification review"),
                    ("SECURITY_APPROVED", "Security approved"),
                    ("PRODUCTION_APPROVED", "Production approved"),
                    ("ACTIVE", "Active"),
                    ("SUSPENDED", "Suspended"),
                    ("REVOKED", "Revoked"),
                    ("DECOMMISSIONED", "Decommissioned"),
                    ("REJECTED", "Rejected"),
                ],
                default="REQUESTED",
                max_length=30,
            ),
        ),
    ]
