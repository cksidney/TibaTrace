from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0003_activation_state_update")]

    operations = [
        migrations.AlterField(
            model_name="providerconfiguration",
            name="provider_type",
            field=models.CharField(max_length=30, choices=[
                ("DHA_HIE", "DHA Health Information Exchange"),
                ("DHA_HWR", "DHA Health Worker Registry"),
                ("PPB_PREMISES", "PPB Premises Registry"),
                ("PPB_PRODUCT_REGISTER", "PPB Product Register"),
                ("PPB_REGULATORY_ALERTS", "PPB Regulatory Alerts"),
                ("PPB_RECALLS", "PPB Product Recalls"),
                ("SHA_INSURER", "SHA / approved insurer"),
                ("MPESA", "Safaricom M-PESA"),
            ]),
        ),
    ]
