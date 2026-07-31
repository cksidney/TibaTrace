from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="posrelease",
            name="minimum_supported_build",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="posrelease",
            name="operations_impact",
            field=models.TextField(blank=True),
        ),
    ]
