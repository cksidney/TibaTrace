# Prescription and Inventory Integration

## Authority

Only a prescription with a current pharmacist context hash can create `DispensingReservation`. The service delegates reservation and FEFO selection to `InventoryReservationService`; dispensing never reimplements FEFO.

The bridge preserves prescription item, inventory reservation, quantity, status, and idempotency. `DispensingAllocation` is derived from immutable reservation ledger entries and records the exact batch and location.

## Supply Transaction

Final supply runs in one database transaction. To keep the existing inventory balance projection non-negative, the reserved bucket is fulfilled immediately before the authoritative `ISSUE` entry is posted. Both operations commit or roll back together, so no external observer can see an intermediate state.

The issue uses source type `MEDICINE_SUPPLY`, source supply ID, source dispensing-line ID, exact location, SKU, batch, quantity, actor, and persistent key. A one-to-one supply-line reference prevents orphan or duplicate issue attribution.

Quarantined, recalled, expired, or non-released batches are rejected.
