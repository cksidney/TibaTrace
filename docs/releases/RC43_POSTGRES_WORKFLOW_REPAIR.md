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

Full clean-checkout SQLite and PostgreSQL 18.6 suites, application/visual gates,
image provenance, verified backup and live checks remain mandatory. Production
is still rc37 until they pass and activation is confirmed. A healthy HTTP endpoint
does not certify the business paths repaired by this candidate.

Unsupported report packs, governed customer agreement/promotion/profile authoring,
provider onboarding, approved Android signing, Manager stock/hardware acceptance
and VPS capacity remain separately open. No real stock, sale, prescription,
password or access grant was created by the isolated verification.
