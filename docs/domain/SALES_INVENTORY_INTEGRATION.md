# Sales Inventory Integration

## Overview
Sales operations in DawaNexus strictly consume inventory domain services (`backend/apps/inventory/services.py`) and never directly mutate inventory tables.

## Integration Boundaries

| Sales Lifecycle Step | Inventory Service Invoked | Ledger Entry Type Posted | Inventory Effect |
| :--- | :--- | :--- | :--- |
| **Order Reservation** | `InventoryReservationService.reserve_stock()` | `RESERVATION` | Soft-reserves quantity against branch available balance |
| **Order Allocation** | `FEFOAllocationService.allocate_stock()` | None (Query only) | Identifies candidate `InventoryBatch` instances ordered by expiry date |
| **Dispatch Order** | `InventoryLedgerService.post_entry()` | `ISSUE` | Immutable ledger entry created; decrements batch on-hand balance |
| **Sales Return Restock** | `InventoryLedgerService.post_entry()` | `RETURN` | Restocks returned batch to inventory location after quality inspection |

## Strict Isolation Guarantees
1. **No Direct Table Writes**: Sales views and services do not execute SQL `UPDATE` or `INSERT` statements on `inventory_inventorybalance`, `inventory_inventorybatch`, or `inventory_inventoryledgerentry`.
2. **Idempotency**: All ledger postings require a unique `idempotency_key` (e.g. `ISSUE_DSP_<line_pk>`). Retries yield the existing ledger record without double-decrementing stock.
3. **Tenant Scoping**: All service calls require explicit `tenant` parameters matching the sales order tenant.
