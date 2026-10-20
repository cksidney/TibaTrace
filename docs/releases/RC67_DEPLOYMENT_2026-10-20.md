# rc67 deployment verification — 20 October 2026

TibaTrace 1.0.0-rc67 was deployed and verified on 20 October 2026
(Africa/Nairobi). Running source: `e5f241f5fef629fae46ec09a843e922a605c37eb`,
tag `tibatrace-v1.0.0-rc67`. This record is a documentation-only follow-up.

## Delivered behavior

Receiving preserves quarantine custody until independently authorized quality
review and release. Release and receipt retries preserve evidence without
duplicating movements. Partial reservations recover their remaining allocations;
reconciliation derives physical and reserved quantities separately from the ledger.
Barcode pack conversions preserve confirmed base-unit evidence.

HQ exposes configured replenishment policies, reviewed procurement demand,
warehouse tasks and readable approval evidence. Return/rejection overlap is
counted once when planning supply. Invalid task reopen requests preserve active
work. Opening setup requires verified acquisition cost and current physical
counts alongside item/unit/price/tax and applicable batch/expiry evidence.
Discarded sources remain auditable and cannot populate active opening stock.

## Validation

[Production Images run 39405800907](https://github.com/cksidney/TibaTrace/actions/runs/39405800907)
passed on the exact source:

- 2,457 SQLite and 2,457 PostgreSQL tests; zero failures, errors or skips.
  Independent coverage checks account for every collected test exactly once.
- HQ 117, Windows 140, Android 41 and shared-package 216 tests; all application
  typechecks and builds passed.
- Both runtime vulnerability scans reported zero findings at build time.
- Source, version, architecture, checksums, five-migration inventory, SBOMs,
  startup checks and exact-source signed provenance passed.

## Production acceptance

A fresh protected database, environment and clinical-object backup was verified.
All five forward migrations applied. API/HQ/Redis health, worker response, source
labels, migration state and served asset hashes passed. Eleven authorized read
routes passed; anonymous access and a cross-tenant inventory lookup were denied.
Route and inventory acceptance used a database-enforced read-only transaction.
Pre/post-deployment inventory and opening-source evidence matched exactly.
No demonstration stock or financial transactions were created.

The production release pointer and migration baseline identify the accepted
source. Detailed backup, recovery and tenant evidence remains private.

Concurrent uncommitted security remediation is outside this tagged release.
Native POS application sources did not change from the preceding server release;
installed client binaries are unchanged. Browser visual inspection was unavailable
because local browser control is disabled; automated UI checks passed.

Inventory acquisition valuation remains separate from statutory accounting,
impairment/NRV policy and general-ledger posting. New quality history requires
the recovery precautions in the [release notes](TIBATRACE_v1.0.0_RC67.md).
