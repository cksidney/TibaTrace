"""Reconcile projections from physical movements and per-lot reservation events."""

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry

PHYSICAL_TYPES = frozenset(
    {
        "RECEIPT",
        "TRANSFER_IN",
        "TRANSFER_OUT",
        "ISSUE",
        "RETURN_IN",
        "RETURN_OUT",
        "ADJUSTMENT_INCREASE",
        "ADJUSTMENT_DECREASE",
        "STOCKTAKE_GAIN",
        "STOCKTAKE_LOSS",
        "WRITE_OFF",
        "DESTRUCTION",
    }
)
DIMENSIONS = ("branch_id", "location_id", "sku_id", "inventory_batch_id")


def ledger_totals(tenant):
    totals = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for entry in (
        InventoryLedgerEntry.all_objects.filter(tenant=tenant)
        .values(*DIMENSIONS, "entry_type", "base_quantity_delta")
        .iterator()
    ):
        values = totals[tuple(entry[key] for key in DIMENSIONS)]
        if entry["entry_type"] in PHYSICAL_TYPES:
            values[0] += entry["base_quantity_delta"]
        elif entry["entry_type"] == "RESERVATION":
            values[1] += entry["base_quantity_delta"]
        elif entry["entry_type"] == "RESERVATION_RELEASE":
            values[1] -= entry["base_quantity_delta"]
    return totals


@transaction.atomic
def reconcile(tenant, *, repair=False):
    # Repair is a maintenance operation. PostgreSQL locks both authoritative
    # events and projections to cover new custody dimensions as well as existing
    # rows. A busy writer fails the operation safely; the operator can retry.
    if repair and connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute(
                "LOCK TABLE inventory_inventoryledgerentry, inventory_inventorybalance IN SHARE ROW EXCLUSIVE MODE"
            )
    # Repairs never change source evidence.
    balances = list(
        InventoryBalance.all_objects.select_for_update(of=("self",))
        .filter(tenant=tenant)
        .select_related("location", "inventory_batch")
    )
    totals = ledger_totals(tenant)
    grouped = defaultdict(list)
    for balance in balances:
        grouped[tuple(getattr(balance, key) for key in DIMENSIONS)].append(balance)
    issues = []
    from apps.inventory.services import InventoryBalanceService

    for key in set(totals) | set(grouped):
        physical, reserved = totals.get(key, (Decimal(0), Decimal(0)))
        if physical < 0 or reserved < 0 or reserved > physical:
            raise ValidationError(
                f"Ledger has invalid physical/reserved quantities for {key}; investigate source events before repair."
            )
        rows = grouped.get(key, [])
        if len(rows) > 1:
            raise ValidationError(f"Duplicate balance dimensions for {key}; reconcile custody identity before repair.")
        if rows:
            current = rows[0]
            expected = InventoryBalance(
                pk=current.pk, tenant=tenant, **dict(zip(DIMENSIONS, key)), on_hand=physical, reserved=reserved
            )
            expected.location = current.location
            expected.inventory_batch = current.inventory_batch
            InventoryBalanceService.derive_buckets(expected)
            fields = (
                "on_hand",
                "reserved",
                "available",
                "quarantined",
                "damaged",
                "expired",
                "recalled",
                "quality_status",
            )
            if any(getattr(current, field) != getattr(expected, field) for field in fields):
                issues.append(str(key))
                if repair:
                    for field in fields:
                        setattr(current, field, getattr(expected, field))
                    current.save()
        elif physical or reserved:
            issues.append(str(key))
            if repair:
                current = InventoryBalance(
                    tenant=tenant, **dict(zip(DIMENSIONS, key)), on_hand=physical, reserved=reserved
                )
                InventoryBalanceService.derive_buckets(current)
                current.save()
    return issues
