import uuid

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.inventory.models import InventoryLedgerEntry


@pytest.mark.django_db
def test_inventory_ledger_entry_is_immutable(
    tenant_a, branch, inventory_location, inventory_batch, sku
):
    entry = InventoryLedgerEntry.objects.create(
        tenant=tenant_a,
        branch=branch,
        location=inventory_location,
        inventory_batch=inventory_batch,
        sku=sku,
        entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
        quantity_delta=10,
        unit="tablet",
        base_quantity_delta=10,
        effective_timestamp=timezone.now(),
        source_document_type="GoodsReceipt",
        source_document_id="GR-100",
        idempotency_key=str(uuid.uuid4()),
    )
    
    # 1. Test save() fails
    with pytest.raises(ValidationError, match="immutable and cannot be modified"):
        entry.notes = "Modified note"
        entry.save()

    # 2. Test delete() fails
    with pytest.raises(ValidationError, match="immutable and cannot be deleted"):
        entry.delete()

    # 3. Test QuerySet.update() fails
    with pytest.raises(ValidationError, match="immutable and cannot be updated"):
        InventoryLedgerEntry.objects.filter(pk=entry.pk).update(notes="Modified note via QS")

    # 4. Test QuerySet.delete() fails
    with pytest.raises(ValidationError, match="immutable and cannot be deleted"):
        InventoryLedgerEntry.objects.filter(pk=entry.pk).delete()

    # Verify still in DB
    assert InventoryLedgerEntry.all_objects.filter(pk=entry.pk).exists()
