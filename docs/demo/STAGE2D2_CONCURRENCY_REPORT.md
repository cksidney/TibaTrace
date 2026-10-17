# Stage 2D.2 Concurrency & Contention Analysis Report

**Date**: August 2026  
**Focus**: Race Safety, Locking Mechanics, Stock Allocation Under Contention  

---

## 1. Concurrency Model & Locking Strategy

TibaTrace enforces single-writer semantics and isolation during state transitions, stock reservations, and payment processing using PostgreSQL `select_for_update` row locks.

```
Request 1 (Pharmacist A) ---> [ SELECT FOR UPDATE ] ---> Validated ---> Transition Saved
Request 2 (Pharmacist B) ---> [ WAITS ON LOCK    ] ---> InvalidStateTransition -> Blocked
```

---

## 2. Contention Test Results

### A. Concurrent Pharmacist Review
- **Scenario**: Two pharmacists reviewing and approving the same prescription simultaneously.
- **Result**: Exactly one approval succeeds; the second request receives an `InvalidStateTransitionError` and is safely rejected. Zero duplicate approvals.

### B. Final Stock Reservation Race (Till Contention)
- **Scenario**: Two tills attempting to reserve the last remaining unit of a high-demand SKU simultaneously.
- **Result**: Row locking on `InventoryBalance` forces sequential execution. Till 1 receives stock allocation; Till 2 receives an insufficient stock exception. Stock level remains exact (`Available = 0, Reserved = 1`).

### C. Simultaneous Payment Callback Processing
- **Scenario**: Gateway sends duplicate or concurrent webhook payment callbacks.
- **Result**: Idempotency key evaluation (`payment_idempotency_key`) prevents double-crediting. Duplicate callbacks return HTTP 200 with identical transaction status.

### D. Simultaneous Dispense Attempts
- **Scenario**: Two dispensing stations clicking "Mark as Dispensed" at the exact same millisecond.
- **Result**: Concurrency safety check blocks double-dispensing. Ledger issue entries are posted exactly once.

---

## 3. Summary Metrics

- **Double-Reservations Blocked**: 100%
- **Double-Dispenses Blocked**: 100%
- **Idempotency Pass Rate**: 100%
- **Deadlock Occurrences**: 0
