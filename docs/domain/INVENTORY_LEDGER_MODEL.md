# Inventory Ledger Model

The DawaTrace Inventory module uses an **append-only ledger** for all stock movements.
Instead of updating "current stock" fields directly, we record the delta of every transaction and compute the current stock as the sum of all historical entries.

## Core Entities

1. **Inventory Location**: A physical or logical storage area within a branch (e.g., Main Store, Dispensary, Quarantine, Damaged Goods).
2. **Inventory Batch**: Represents a specific manufactured batch of a Commercial SKU. This tracks expiry dates, manufacturer batch numbers, and quality status (e.g., RELEASED, QUARANTINED, EXPIRED).
3. **Inventory Ledger Entry**: An immutable record of an inventory transaction. Includes the entry type, quantity delta (always positive for receipts/gains, negative for issues/losses), the source document that authorized it, and an idempotency key.
4. **Inventory Balance**: A materialized view (projection) of the ledger for a specific SKU and Batch at a Location. It stores `on_hand`, `reserved`, `available`, `quarantined`, `damaged`, and `expired` quantities.

## Ledger Entry Types

* **RECEIPT**: Stock received from a supplier (increases on-hand).
* **ISSUE**: Stock dispensed or issued (decreases on-hand).
* **TRANSFER_OUT** / **TRANSFER_IN**: Stock moved between locations.
* **RETURN_OUT** / **RETURN_IN**: Stock returned to supplier or from a patient.
* **ADJUSTMENT_INCREASE** / **ADJUSTMENT_DECREASE**: Manual stock corrections.
* **STOCKTAKE_GAIN** / **STOCKTAKE_LOSS**: Variances found during physical counts.
* **EXPIRY**: Stock moved to expired status.
* **WRITE_OFF** / **DESTRUCTION**: Permanent removal of stock.
* **RESERVATION** / **RESERVATION_RELEASE**: Temporary holds on available stock.

## Balance Recalculation

If the materialized balances become corrupt or out of sync, they can be completely dropped and re-computed from the beginning of time using the `InventoryBalanceService.rebuild_all_balances()` method.

## Quality and Expiry

The quality status of inventory is driven by the `InventoryBatch`. If a batch's quality status changes (e.g. from RELEASED to QUARANTINED), all projected balances for that batch are updated to reflect the new status. Availability is derived dynamically based on location capabilities and batch quality status.
