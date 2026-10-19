# TibaTrace 1.0.0-rc63 — tenant item onboarding and inventory controls

Adds a governed first item-list upload for tenant setup. Source catalogue data
is retained as review evidence and does not create saleable stock. Managers can
download a blind opening stocktake sheet, record actual quantities and medicine
batches, complete catalogue and price review, and release opening stock through
the existing approval workflow.

Closes inventory workflow gaps across receipt quarantine, stocktake counting,
transfers, supplier returns, write-offs, adjustments and acquisition-cost
valuation. Physical variances and costs require independent approval; movement
and valuation evidence stays tenant-scoped and append-only. Full stocktakes use
their opening snapshot, and partial receipt release moves only the accepted
quantity into saleable custody.

## Database and compatibility

This release adds migrations for non-medicine catalogue items, internal
non-expiring custody lots, supplier-return approval and credit reconciliation,
inventory exception requests, and acquisition-cost evidence. Existing medicine
records keep their medicine classification and continue through the existing
clinical dispensing gates. The migrations are additive; no tenant stock or
financial records are seeded or rewritten by deployment.

Back up PostgreSQL and verify the release migration inventory before activation.
Retain the previous immutable backend and HQ images. If application rollback is
needed after new inventory evidence has been recorded, leave the expanded schema
in place; restore the database only under the separately verified recovery plan.

## Release gates

Publish and activate this candidate only after the exact-tag production image
workflow passes its backend, PostgreSQL, frontend, migration, image-security and
container-startup gates. Production acceptance must verify API/HQ health,
runtime source labels, migrations, tenant isolation, worker health and backup
integrity. No clinical, stock or financial test records should be created in
production during acceptance.

## Candidate correction

Supersedes rc62, which was not deployed. The full release suites found a demo
reseeding identity defect and stale valuation/migration test contracts. Demo
reseeding now reuses its established inventory SKU; valuation tests exercise
explicit unvalued costs and permissions, and the migration guard enumerates all
five new migrations without weakening the inventory check.
