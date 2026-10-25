from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("patients", "0002_patientclinicalsummary_patientconditionsummary_and_more")]

    operations = [
        migrations.AddField(
            model_name="patientidentifier",
            name="lookup_key_id",
            field=models.CharField(blank=True, default="", editable=False, max_length=64),
        ),
    ]
