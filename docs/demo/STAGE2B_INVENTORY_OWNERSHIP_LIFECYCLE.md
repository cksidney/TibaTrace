# Stage 2B.2B — Inventory Ownership & Quality Release Lifecycle

## Overview

Stage 2B.2B establishes authoritative inventory ownership across TibaTrace platform. Stock cannot become available for dispensing or order allocation without passing through quality release, atomic ledger posting, and balance projection.

---

## 1. Inventory Ownership Lifecycle

The only permitted path from physical receipt to available stock is:

```
  ReceivedBatch (QUARANTINED)
           │
           ▼
     QualityDecision (APPROVE_FOR_RELEASE)
           │
           ▼
  release_batch() ➔ (RELEASED / PARTIALLY_RELEASED)
           │
           ▼
  post_receipt() ➔ accepted_quantity only
           │
           ▼
  InventoryLedgerService.post_entry() (Append-only ledger)
           │
           ▼
  InventoryBalanceService.rebuild_all_balances() (Projection)
           │
           ▼
  InventoryBatch Projection
           │
           ▼
  Available Inventory (FEFO Allocation Eligible)
```

No shortcuts or direct state mutations are permitted.

---

## 2. Quality Release Gate Rules

`release_batch()` enforces an 11-point quality gate. Release is refused if any of the following fail:

1. **Goods Receipt**: Associated `GoodsReceipt` exists.
2. **Inspection**: `ReceivingInspection` exists for the receipt.
3. **Quality Decision**: `QualityDecision` exists for the batch.
4. **Releasable Outcome**: `QualityDecision.is_releasable() == True` (`APPROVE_FOR_RELEASE`).
5. **Expiry Date**: Batch is not expired (`expiry_date > as_of`).
6. **Recall Status**: Batch is not subject to a regulatory recall.
7. **Supplier Qualification**: Supplier is active and qualified on the order/receipt date.
8. **Premises Compliance**: Pharmacy premises licence is valid.
9. **Storage Location Compatibility**: Target storage location supports required capabilities (`controlled_drug_capability`, `cold_chain_capability`).
10. **Controlled Medicine Governance**: Controlled SKUs must be assigned to controlled vault locations.
11. **Cold-Chain Evidence**: Cold-chain SKUs must be assigned to cold room/freezer locations.

---

## 3. Partial Release Lifecycle Model

- **Batch Statuses**:
  - `QUARANTINED`: 0 units accepted (100% awaiting decision or held).
  - `PARTIALLY_RELEASED`: Partial quantity accepted ($0 < \text{accepted} < \text{received}$). Remainder stays quarantined.
  - `RELEASED`: 100% accepted ($\text{accepted} == \text{received}$).
- **Single Batch Identity**: One physical batch retains a single manufacturer batch identity. Sub-lots are not created to preserve recall traceability.
- **Posting Scope**: `post_receipt()` operates strictly on `accepted_quantity`. Held or rejected quantities are never posted into inventory balances.

---

## 4. Balance Rebuild & Immutability

- `InventoryBalance` is a derived projection, never updated directly by business operations.
- `InventoryBalanceService.rebuild_all_balances()` wipes all balances and reconstructs them chronologically from `InventoryLedgerEntry`.
- `available` balance calculation excludes `quarantined`, `damaged`, `expired`, and non-available storage areas.

---

## 5. FEFO Allocation Readiness

- `FEFOAllocationService.allocate_stock()` operates strictly on `available > 0` stock in `RELEASED` / `PARTIALLY_RELEASED` batches.
- Allocations sort strictly by earliest expiry date (`expiry_date ASC, batch_id ASC`).
- Quarantined, held, recalled, expired, or rejected stock is completely excluded.
