# TibaTrace 1.0.0-rc65 — inventory workflow safeguards

Fixes four stock defects: quality release could recreate supplier-returned goods,
release could omit an independent quality decision, integrity repair could add
reservation quantities to physical stock, and partial reservations could not
release their remainder. Release and reservation transitions now lock their
source evidence and retry safely. Expired reservations with explicit deadlines
are processed by tenant-scoped scheduled maintenance.

Manual and scanned receiving share quarantine and independent release rules.
Non-expiring supplies use internal custody lots. Barcode packs normalize once
into confirmed stock/selling units and preserve conversion evidence. Purchase
quantities and costs identify that same base unit. An arrival inspection alone
cannot accept quantities or satisfy invoice matching.

Adds configured safety/reorder/target policies, hourly demand planning, reviewed
requisition creation and warehouse coordination linked to authoritative stock
documents. HQ exposes these workflows through compact intake dialogs. Inventory
exception approval includes item, unit, custody, current quantities, proposed
effect and acquisition evidence.

Opening setup requires verified acquisition cost as well as item/unit/price/tax
review, current physical counts, medicine mapping and actual batches/expiry.
Discarded draft imports retain their source and audit evidence, leave active
onboarding and cannot block corrected uploads or be revived through review.
No tenant opening quantities, prices, tax categories or reorder targets are
inferred or seeded by deployment.

## Schema and rollback

Five migrations add operational planning/task evidence, scanned-unit evidence,
optional supply expiry, receipt/release retry evidence and numbered quality
reinspections. The old one-decision constraint is replaced by an explicit
revision key and one-to-one supersession link. Earlier decisions are retained;
quality decisions protect their source receipt/batch against cascading deletion.
The release evidence guard recognizes only that exact constraint replacement.

Back up the database before migration. Prefer a forward fix after new quality
revisions or release events exist: rc63 does not understand the revised quality
history and is unsuitable for unrestricted write rollback. Preserve the expanded
schema and immutable evidence; a database restore requires the verified recovery
plan and reconciliation of subsequent business transactions.

## Acceptance

Require the exact-source SQLite/PostgreSQL suites, all frontend gates, migration
inventory, image scans, signed build evidence and container startup checks before
activation. Verify runtime source labels, API/HQ health, migrations and workers
after activation. Use isolated synthetic fixtures for stock-cycle acceptance;
never create demonstration stock or financial transactions in a live tenant.

Operational workflow: [Inventory operating workflow](../inventory/INVENTORY_WORKFLOW.md).
Inventory acquisition valuation remains separate from statutory accounting,
impairment/NRV policy and general-ledger posting.

## Validation follow-up

Legacy HQ sample journeys now record the same independent per-batch decision as
live receiving. Mobility fixtures use aware future reservation deadlines and
explicitly age only synthetic expiry cases. Returns of already rejected stock
are excluded once from release eligibility, and dispatch reconciles the held
receipt quantities. Reservation retries remain idempotent after their deadline.

Replenishment subtracts overlapping quality rejection/return claims once per
batch. One lot’s rejected units cannot erase another lot’s pending supply.
