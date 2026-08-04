# Stage 2C — Stock Mobility & Reservation Engine Lifecycle

## Overview

Stage 2C establishes authoritative inter-branch stock mobility and inventory reservation locking across TibaTrace platform. Physical inventory movement between locations and stock reservations for pending fulfilment operate strictly through authoritative business services (`StockTransferService`, `InventoryReservationService`, `FEFOAllocationService`, `InventoryLedgerService`, and `InventoryBalanceService`).

---

## 1. Inter-Branch Stock Transfer Lifecycle

```
  REQUESTED (StockTransferService.request_transfer)
      │
      ├───────────────────────┐
      ▼                       ▼
   APPROVED                REJECTED (StockTransferService.reject_transfer)
      │
      ▼
   DISPATCHED / IN_TRANSIT (StockTransferService.allocate_and_dispatch)
      │  └── FEFO Allocation + TRANSFER_OUT Ledger Entry
      ▼
   RECEIVED / POSTED (StockTransferService.receive_transfer)
      │  └── TRANSFER_IN Ledger Entry
      ▼
   COMPLETED
```

### Domain Rules:
- **Segregation of Duties**: The user requesting a transfer (`requested_by`) cannot approve their own transfer (`approved_by`).
- **FEFO Allocation**: Outbound transfer dispatch allocates batches strictly via `FEFOAllocationService.allocate_stock()`. Quarantined, held, expired, or rejected batches are excluded.
- **Inventory Balance Integrity**: Every transfer dispatch posts a `TRANSFER_OUT` ledger entry, and every transfer receipt posts a `TRANSFER_IN` ledger entry. Total `TRANSFER_OUT` equals total `TRANSFER_IN` with zero stock loss or leak.

---

## 2. Inventory Reservation & Allocation Locking Lifecycle

```
  reserve_stock()
      │
      ├──────► FEFO Allocation Lock
      │
      ├──────► RESERVATION Ledger Entry (Reduces Available Balance)
      │
      ├───► FULFILLED (Consumption / Sales Dispatch)
      │
      ├───► EXPIRED (expire_reservation -> RESERVATION_RELEASE Ledger Entry)
      │
      └───► RELEASED (release_reservation -> RESERVATION_RELEASE Ledger Entry)
```

### Domain Rules:
- **Balance Impact**: Reservations reduce `available` balance while keeping `on_hand` balance unchanged. Neither ledger balances nor `InventoryBatch` quantities are mutated directly.
- **Release / Expiry**: Cancelled or expired reservations post a `RESERVATION_RELEASE` ledger entry restoring `available` quantity.

---

## 3. Boundary & Validation Rules

- **Zero Balance Drift**: `InventoryBalanceService.rebuild_all_balances()` rebuilds all balances from scratch with 0 drift.
- **Zero Negative Stock**: `on_hand >= 0` and `available >= 0` enforced across all locations.
- **Idempotency & Resume**: Re-running Stage 2C produces 0 duplicate transfers, 0 duplicate reservations, and 0 duplicate ledger entries.
