"""Collapse payment_gate_state + payment_status into one canonical payment_state.

The episode previously carried two payment fields that could disagree:

  payment_gate_state  authoritative -- what MedicineSupplyService actually gated
                      supply on. Default NOT_REQUIRED.
  payment_status      a POS-only mirror added later. Default PENDING, and only
                      ever written by the POS payment action.

Because non-POS dispensing never wrote payment_status, every clinically
dispensed episode carried a meaningless PENDING in it. This migration keeps the
authoritative value and preserves any evidence of settlement recorded by the POS.
"""
from django.db import migrations, models

# Reverse mapping for states that did not exist before this migration. This is
# lossy -- the canonical model draws distinctions the old pair could not express
# -- but it restores a coherent pre-migration value for every row.
REVERSE_GATE_MAP = {
    "PARTIALLY_PAID": "PENDING",
    "CANCELLED": "FAILED",
    "REVERSAL_PENDING": "PAID",
    "REVERSED": "FAILED",
    "REFUNDED": "FAILED",
}


def canonical_state(gate, status):
    """Map the legacy field pair onto one canonical state.

    Settlement evidence wins. Legacy POS payments wrote payment_status='PAID'
    without always advancing the gate, so trusting the gate alone would silently
    forget that money had been taken.
    """
    return "PAID" if status == "PAID" else (gate or "NOT_REQUIRED")


def legacy_states(state):
    """Inverse of canonical_state: (payment_gate_state, payment_status)."""
    state = state or "NOT_REQUIRED"
    gate = REVERSE_GATE_MAP.get(state, state)
    # payment_status only ever meaningfully held PAID; everything else was its
    # untouched default.
    return gate, ("PAID" if state == "PAID" else "PENDING")


def forwards(apps, schema_editor):
    Episode = apps.get_model("prescription", "DispensingEpisode")
    for episode in Episode.objects.all().iterator():
        episode.payment_state = canonical_state(
            episode.payment_gate_state, episode.payment_status
        )
        episode.save(update_fields=["payment_state"])


def backwards(apps, schema_editor):
    Episode = apps.get_model("prescription", "DispensingEpisode")
    for episode in Episode.objects.all().iterator():
        gate, status = legacy_states(episode.payment_state)
        episode.payment_gate_state = gate
        episode.payment_status = status
        episode.save(update_fields=["payment_gate_state", "payment_status"])


class Migration(migrations.Migration):
    dependencies = [
        ("prescription", "0009_dispensingepisode_payment_idempotency_key_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dispensingepisode",
            name="payment_state",
            field=models.CharField(
                choices=[
                    ("NOT_REQUIRED", "Not required"),
                    ("PENDING", "Pending"),
                    ("AUTHORIZED", "Authorized"),
                    ("PARTIALLY_PAID", "Partially paid"),
                    ("PAID", "Paid"),
                    ("WAIVED", "Waived"),
                    ("FAILED", "Failed"),
                    ("CANCELLED", "Cancelled"),
                    ("REVERSAL_PENDING", "Reversal pending"),
                    ("REVERSED", "Reversed"),
                    ("REFUNDED", "Refunded"),
                ],
                default="NOT_REQUIRED",
                max_length=30,
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="dispensingepisode", name="payment_gate_state"),
        migrations.RemoveField(model_name="dispensingepisode", name="payment_status"),
    ]
