# rc43 candidate — PostgreSQL workflow repair

Includes the held commercial pricing, source-report, maintenance-admin and HQ
workspace scope of rc41/42, plus the real PostgreSQL workflow repairs described
in [the defect evidence](POSTGRES_WORKFLOW_DEFECTS_2026-10-14.md).

All 99 affected checkout/refund, stocktake, onboarding and B2B fulfilment tests
pass on isolated local PostgreSQL 18.1/UTF-8 and SQLite. All 69 commercial,
source-report, maintenance-admin and lookup checks also pass on PostgreSQL.
Tests also cover multiple
locations/batches in FEFO order, unbatched recounts and fractional quantities.
Lookup auditing is unchanged and clean; no additional schema change is required
beyond reviewed sales 0005. Native Windows/Android source is unchanged, so
Windows remains signed managed-device 1.0.5 and Android remains unpublished.

The live VPS was inspected and runs PostgreSQL 16.15. The initial rc43 production
and all-surface workflows already run PostgreSQL 18.6; neither is represented as
production-major parity. A separate full PostgreSQL 16 validation is required
against the exact rc43 tag/commit before activation. The reusable gate's default
was aligned to major 16 for subsequent candidates, without changing rc43 runtime
code, its immutable tag or the deployed database version.

Full clean-checkout SQLite, PostgreSQL 18.6 and production-major PostgreSQL 16 suites, application/visual gates,
image provenance, verified backup and live checks remain mandatory. Production
is still rc37 until they pass and activation is confirmed. A healthy HTTP endpoint
does not certify the business paths repaired by this candidate.

Unsupported report packs, governed customer agreement/promotion/profile authoring,
provider onboarding, approved Android signing, Manager stock/hardware acceptance
and VPS capacity remain separately open. No real stock, sale, prescription,
password or access grant was created by the isolated verification.
