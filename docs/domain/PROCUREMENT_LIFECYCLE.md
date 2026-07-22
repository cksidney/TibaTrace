# Procurement Lifecycle & Commercial Commitment Architecture

## Overview

DawaTrace strictly separates internal demand requests (Purchase Requisitions) from external commercial commitments (Purchase Orders).

---

## 1. Purchase Requisition Lifecycle

```text
DRAFT ──> SUBMITTED ──> UNDER_REVIEW ──> APPROVED ──> PARTIALLY_ORDERED / FULLY_ORDERED ──> CLOSED
                            │
                            └──> REJECTED / CANCELLED
```

* **Purpose**: Internal demand signal initiated by branch pharmacists or store managers.
* **Invariant**: Does not create supplier liability or inventory. Must reference authoritative Phase 3.1 `CommercialSKU` records.

---

## 2. Purchase Order Lifecycle & Revision Control

```text
DRAFT ──> SUBMITTED ──> APPROVED ──> SENT ──> ACKNOWLEDGED ──> PARTIALLY_RECEIVED ──> FULLY_RECEIVED ──> CLOSED
```

* **Purpose**: Legally binding commercial commitment to an approved supplier.
* **Revision Control**: Approved POs cannot be silently modified. Any change in price, quantity, or supplier creates an immutable `PurchaseOrderRevision` record with audit history.
