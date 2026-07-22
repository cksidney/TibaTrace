# Goods Receiving & Batch Capture Architecture

## Overview

Physical receiving of pharmaceutical goods is decoupled from quality release and inventory stock ledger entry.

---

## Goods Receipt Lifecycle

```text
DRAFT ──> RECEIVING ──> RECEIVED ──> UNDER_INSPECTION ──> PARTIALLY_ACCEPTED / ACCEPTED ──> CLOSED
                                              │
                                              └──> REJECTED / CANCELLED
```

---

## Batch & Expiry Capture (`ReceivedBatch`)

Every physical delivery creates explicit `ReceivedBatch` records capturing:
* Manufacturer Batch Number
* Expiry Date
* Manufacture Date
* Temperature Excursion Flag
* Received Quantity, Accepted Quantity, Quarantined Quantity, Rejected Quantity

### Quality Status Progression
```text
PENDING_INSPECTION ──> QUARANTINED ──> RELEASED
                            │               │
                            └──> REJECTED   └──> RETURN_PENDING ──> RETURNED / DESTROYED
```
Stock remains unavailable for dispensing/sales until `quality_status == 'RELEASED'`.
