from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.inventory.models import InventoryBalance


@pytest.mark.django_db
def test_check_inventory_integrity_clean(
    tenant_a, branch, inventory_location, inventory_batch, sku, django_assert_num_queries
):
    # Setup some legitimate data
    from apps.inventory.models import InventoryLedgerEntry
    from apps.inventory.services import InventoryLedgerService

    InventoryLedgerService.post_entry(
        tenant=tenant_a,
        branch=branch,
        location=inventory_location,
        sku=sku,
        entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
        quantity_delta=100,
        unit="tablet",
        base_quantity_delta=100,
        effective_timestamp="2023-01-01T00:00:00Z",
        source_document_type="GoodsReceipt",
        source_document_id="GR-001",
        idempotency_key="receipt_1",
        inventory_batch=inventory_batch,
    )

    call_command("check_inventory_integrity", tenant_id=str(tenant_a.id))


@pytest.mark.django_db
def test_check_inventory_integrity_mismatch_and_repair(
    tenant_a, branch, inventory_location, inventory_batch, sku
):
    from apps.inventory.models import InventoryLedgerEntry
    from apps.inventory.services import InventoryLedgerService

    InventoryLedgerService.post_entry(
        tenant=tenant_a,
        branch=branch,
        location=inventory_location,
        sku=sku,
        entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
        quantity_delta=100,
        unit="tablet",
        base_quantity_delta=100,
        effective_timestamp="2023-01-01T00:00:00Z",
        source_document_type="GoodsReceipt",
        source_document_id="GR-001",
        idempotency_key="receipt_1",
        inventory_batch=inventory_batch,
    )

    InventoryBalance.all_objects.filter(tenant=tenant_a).update(on_hand=50, available=50)

    # Running check should fail
    with pytest.raises(SystemExit):
        call_command("check_inventory_integrity", tenant_id=str(tenant_a.id))

    # Running with repair should fix it
    call_command("check_inventory_integrity", "--repair-projections", tenant_id=str(tenant_a.id))

    balance = InventoryBalance.all_objects.get(tenant=tenant_a)
    assert balance.on_hand == Decimal("100.0000")
    assert balance.available == Decimal("100.0000")


@pytest.mark.django_db
def test_rebuild_inventory_balances_command(
    tenant_a, branch, inventory_location, inventory_batch, sku
):
    from apps.inventory.models import InventoryLedgerEntry
    from apps.inventory.services import InventoryLedgerService

    InventoryLedgerService.post_entry(
        tenant=tenant_a,
        branch=branch,
        location=inventory_location,
        sku=sku,
        entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
        quantity_delta=100,
        unit="tablet",
        base_quantity_delta=100,
        effective_timestamp="2023-01-01T00:00:00Z",
        source_document_type="GoodsReceipt",
        source_document_id="GR-002",
        idempotency_key="receipt_2",
        inventory_batch=inventory_batch,
    )

    InventoryBalance.all_objects.filter(tenant=tenant_a).update(on_hand=50, available=50)

    call_command("rebuild_inventory_balances", tenant=tenant_a.slug)

    balance = InventoryBalance.all_objects.get(tenant=tenant_a)
    assert balance.on_hand == Decimal("100.0000")


@pytest.mark.django_db
def test_seed_inventory_command(tenant_a, branch, sku):
    call_command("seed_inventory", tenant=tenant_a.slug)
    
    # Check that a ledger entry and a balance were created
    balance = InventoryBalance.all_objects.get(tenant=tenant_a, sku=sku)
    assert balance.on_hand == Decimal("1000.0000")
