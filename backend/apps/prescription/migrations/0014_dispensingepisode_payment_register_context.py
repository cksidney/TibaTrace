import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pos_shift", "0002_shiftreport_shiftreportreprint_and_more"),
        ("prescription", "0013_paymenttender_operator_shift_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dispensingepisode",
            name="payment_device_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="dispensingepisode",
            name="payment_operator_shift",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payment_episodes", to="pos_shift.operatorshift"),
        ),
        migrations.AddField(
            model_name="dispensingepisode",
            name="payment_register_session",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payment_episodes", to="pos_shift.registersession"),
        ),
    ]
