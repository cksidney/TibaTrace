# rc63 deployment verification — 19 October 2026

TibaTrace 1.0.0-rc63 was deployed and verified on 19 October 2026
(Africa/Nairobi). Server source: `17092bf4021991f13f938beda80f9e4512d423b5`,
tag `tibatrace-v1.0.0-rc63`. This report is a documentation-only follow-up;
the running application remains the tagged source.

## Delivered behavior

HQ supports tenant item-list upload followed by a blind opening stocktake
template and governed count upload, review and stock release. Imported source
quantities remain evidence rather than automatically becoming saleable stock.
Inventory controls cover receiving quarantine and partial release, stocktake
counts, independent approval for stock/cost exceptions, supplier returns and
credit reconciliation, transfer shortages and acquisition-cost valuation.
Unknown acquisition costs remain explicitly unvalued.

rc62 was not deployed. rc63 corrects the demo reseeding identity defect and
refreshes valuation and migration test contracts while retaining their guards.

## Release validation

[Production Images run 39225222571](https://github.com/cksidney/TibaTrace/actions/runs/39225222571)
passed on the exact rc63 source:

- 2,419 SQLite and 2,419 PostgreSQL tests; zero failures, errors or skips.
- HQ 113, Windows POS 140, Android 41 and shared-package 216 tests; application
  typechecks and builds passed.
- Backend dependency audit and both runtime vulnerability scans reported no
  findings at build time.
- Release checksums, architecture/source labels, migration inventory, runtime
  smoke checks, SBOMs and exact-source GitHub provenance passed.

## Deployment acceptance

All five migrations applied successfully. Runtime source labels, public health,
served asset integrity, current migrations and worker response passed.
Authenticated item setup, blind count template, valuation and inventory read
routes passed. Cross-tenant access was refused; anonymous access was denied.
Acceptance ran in a read-only database transaction, and inventory counts were
unchanged. No stock, clinical or financial test records were created.

The deployment retains protected backup, migration and acceptance evidence and
prior-release recovery assets. The migration baseline was advanced to the
verified source. Detailed operational paths and tenant/infrastructure metadata
are retained in the private deployment evidence rather than this public report.

Windows POS 1.1.1 build 18 and Android 1.1.0 build 7 were already published in the
tenant download catalogue. Server deployment does not replace installed clients.
