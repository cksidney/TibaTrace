from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0004_promotionrule_deliveryrecord_idempotency_key_and_more")]

    operations = [
        migrations.RemoveConstraint(model_name="pricelistentry", name="uq_pricelistentry_sku_date"),
        migrations.AddConstraint(model_name="pricelistentry", constraint=models.UniqueConstraint(
            fields=("price_list", "sku", "minimum_quantity", "effective_from"), name="uq_pricelistentry_break_date")),
    ]
