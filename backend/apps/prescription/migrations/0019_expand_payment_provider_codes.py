from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("prescription", "0018_fiscal_print_documents"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymenttender",
            name="provider",
            field=models.CharField(default="MANUAL", max_length=64),
        ),
        migrations.AlterField(
            model_name="paymentattempt",
            name="provider",
            field=models.CharField(max_length=64),
        ),
        migrations.AlterField(
            model_name="paymentproviderevent",
            name="provider",
            field=models.CharField(max_length=64),
        ),
    ]
