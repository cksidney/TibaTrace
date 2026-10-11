# Workflow closure evidence — 11 October 2026

This is a living evidence record, not a certification certificate. A healthy
HTTP endpoint or passing isolated test is not full business acceptance.

## Release status

- Production read-only check: rc22 / `1783e39d1607eb7945a48a1b99c4d2450c59eb77`.
  API, HQ and Redis healthy; worker and beat running. No production writes have
  been made during the rc23/rc24 closure work as of this record.
- rc23 commit `48b40458df71e3494016863c996f774fdbb600cb` failed its mandatory
  GitHub gate: 1,868 passed, one baseline test skipped by shallow checkout,
  eight demo readiness setup errors. Images were not published by that run.
- rc24 fixes the eligible-stock reservation planning error and requests full
  Git history so baseline evidence no longer skips. Its full CI verdict is pending.

## Verified locally

- All eight affected Stage 2D.1 readiness tests passed after the stock-planning
  fix, including validator, no-dispense boundary and idempotent resume.
- 30 activation/report/migration tests passed with actual migrations. A later
  48-test targeted run passed after adding non-empty inventory-report checks.
- Production-mode activation tests reject missing/mismatched/revoked device
  proof and allow valid proof to reach ordinary business request validation.
- UI tests: HQ 52, Android 41, Windows 95, shared 201 passing (389 total).
  Includes independent approve/reject/revoke routing and unavailable-report UI.
- All application typechecks and JS/main builds passed locally. Local Node 20
  is outside the declared Node 22 support range, so the Node 22 CI gate remains
  authoritative. These local results are not installer/hardware acceptance.
- Ruff passes; Django model/migration drift check reports no changes.

## Boundaries still requiring closure

- Commit-matched, full CI test evidence and immutable published image digests.
- Backup/restore acceptance and safe production deployment/rollback evidence.
- Native signed installer publication and real Manager device/hardware tests.
  Managers agreed to arrange the existing Android signing key via secret setup;
  no key or password has been provided in chat or added to the repository.
- Actual stock units, pack conversions, batches, expiry and licences: Managers
  must confirm them. Unconfirmed source items must not be made saleable.
- Retail checkout/stock/receipt/refund/till closure integration, current tenant
  role grants, catalogue publication and independent commercial/clinical review.
- Seventeen report packs have explicit source queries/current snapshots. Other
  catalogue packs remain disabled/501, not represented as successful snapshots.
- Official external endpoints and acceptance: user requested templates only.
  Provisioning creates disabled metadata, not connections, regulator push feeds
  or national licence validation. Simulated providers cannot settle real tenants.
- Existing untracked Stage 2D.2 files and certification reports remain user drafts,
  outside release bundles. Their claims are not accepted as verification evidence.

VPS disk headroom is about 3.7 GB (90% used). Do not prune unrelated services,
live data, rollback assets or user drafts to create space.
