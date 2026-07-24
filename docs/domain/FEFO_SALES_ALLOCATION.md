# FEFO Sales Allocation

## Overview
FEFO (First-Expired, First-Out) allocation ensures that pharmaceutical products with the nearest expiration date are allocated to sales orders first, minimizing wastage and complying with GDP (Good Distribution Practice) guidelines.

## Allocation Algorithm
`SalesAllocationService.allocate_order()` calls `FEFOAllocationService.allocate_stock()`:

```sql
SELECT * FROM inventory_inventorybalance
WHERE tenant_id = :tenant_id
  AND branch_id = :branch_id
  AND sku_id = :sku_id
  AND available > 0
  AND inventory_batch_id NOT IN (:excluded_batches)
ORDER BY inventory_batch__expiry_date ASC, inventory_batch__id ASC
```

## Batch Selection Rules
1. **Expiry Date Primary Ordering**: Batches with `expiry_date` nearest to current date are selected first.
2. **Quarantine & Hold Exclusion**: Batches with `quality_status != 'RELEASED'` or `recall_status != 'NONE'` are automatically excluded.
3. **Minimum Remaining Shelf Life**: If a customer or sales order line specifies `minimum_shelf_life_days`, batches with fewer remaining shelf-life days are excluded.
4. **Partial Allocation Handling**: If available stock across released batches is less than requested, `SalesOrderAllocation` records are created for available quantities and order status transitions to `PARTIALLY_ALLOCATED`.
