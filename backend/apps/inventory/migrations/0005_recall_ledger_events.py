from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0004_replenishmentrecommendation_warehousetask_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="inventoryledgerentry",
            name="chk_ledger_delta_nonzero",
        ),
        migrations.RemoveConstraint(
            model_name="inventoryledgerentry",
            name="chk_ledger_base_delta_nonzero",
        ),
        migrations.AddConstraint(
            model_name="inventoryledgerentry",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        entry_type__in=["RECALL_HOLD", "RECALL_RELEASE"],
                        quantity_delta=0,
                        base_quantity_delta=0,
                    )
                    | (
                        ~Q(entry_type__in=["RECALL_HOLD", "RECALL_RELEASE"])
                        & ~Q(quantity_delta=0)
                        & ~Q(base_quantity_delta=0)
                    )
                ),
                name="chk_ledger_recall_zero_or_delta",
            ),
        ),
    ]
