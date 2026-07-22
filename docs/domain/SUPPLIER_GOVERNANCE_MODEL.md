# Supplier Governance & Qualification Model

## Overview

The DawaTrace Supplier Master represents commercial counterparties distinct from drug manufacturers, marketing authorisation holders, and healthcare organizations.

---

## Supplier Lifecycle State Machine

```text
PROSPECTIVE
  └──> UNDER_REVIEW
         └──> APPROVED ──> ACTIVE
                │            │
                └──> SUSPENDED / DISQUALIFIED / ARCHIVED
```

* **`PROSPECTIVE`**: Initial supplier registration. No purchase requisitions or purchase orders permitted.
* **`UNDER_REVIEW`**: Compliance documentation and licence verification in progress.
* **`APPROVED`**: Supplier qualification verified by compliance officer. Eligible for product agreements.
* **`ACTIVE`**: Fully operational supplier enabled for purchase order issuance.
* **`SUSPENDED`**: Temporarily blocked due to quality, licence expiry, or audit issues. Blocked from new purchase orders.
* **`DISQUALIFIED`**: Permanently barred from doing business due to severe compliance failure.
* **`ARCHIVED`**: Historical record retention.

---

## Supplier Qualification & Compliance Evidence

Suppliers must maintain valid compliance evidence under `SupplierQualification`:
* Wholesale Dealer Licence
* Business Registration
* Tax Compliance Certificate
* Good Distribution Practice (GDP) Certificate
* Cold-Chain Capability Authorization
* Controlled Drug Distribution Licence

Qualification statuses: `PENDING`, `VERIFIED`, `REJECTED`, `EXPIRED`, `REVOKED`.
