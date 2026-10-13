from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("medicines", "0004_legacy_catalogue_setup")]
    operations = [migrations.AddField(model_name="legacycatalogueitem", name="completion", field=models.JSONField(blank=True, default=dict))]
