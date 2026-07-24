from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete, pre_save
from django.dispatch import receiver

from .models import InventoryLedgerEntry


@receiver(pre_save, sender=InventoryLedgerEntry)
def prevent_inventory_ledger_update(sender, instance, **kwargs):
    if instance.pk is not None:
        if InventoryLedgerEntry.all_objects.filter(pk=instance.pk, tenant=instance.tenant_id).exists():
            raise ValidationError("InventoryLedgerEntry records are immutable and cannot be modified.")

@receiver(pre_delete, sender=InventoryLedgerEntry)
def prevent_inventory_ledger_delete(sender, instance, **kwargs):
    raise ValidationError("InventoryLedgerEntry records are immutable and cannot be deleted.")
