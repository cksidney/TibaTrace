# rc44 release verification — 14 October 2026

**Status: rc44 deployed and post-activation checks passed.**

Candidate: `tibatrace-v1.0.0-rc44`, runtime source
`19007332d078f1dbff5e033bffae9ce4963d73d0`. The deployment baseline is
`093910f58b6e1916c3cc35851d41c2ee76551484`. GitHub main was checked during
verification and contains no changes ahead of this candidate. Incomplete
untracked Stage 2D.2 code and user documents are preserved and excluded.

## Independently checked evidence

- [CI 38522867118](https://github.com/cksidney/TibaTrace/actions/runs/38522867118):
  exact-source PostgreSQL **16.15** suite passed **2,137 tests**, with no failures,
  errors or skips. `source-database.json` confirms the actual Django vendor,
  server version and source revision; provisioning a database alone is not cited.
  Shared/HQ/Windows/Android gates and the visual suites passed. The visual job
  records 104 passes at each of its two console widths (1280 and 1024); these
  are not Android hardware or mobile-device acceptance. Full repository validation
  passed its migration rollback/reapply, seed-replay integrity, contract, tenant
  safety and runtime audits. Its shallow-checkout test result is 2,136 passed and
  one baseline-history test skipped; the full-history production suite passed
  that test. Bandit, baseline secret scan and online dependency audit have no
  findings. Shared-workspace TypeScript/build/test checks were executed in their
  separate successful job. The generic legacy validation manifest still carries
  a historical project-version label and deferred external-release placeholders;
  authoritative release identity is the exact source SHA, canonical VERSION and
  verified production manifest. Actual container/provenance/native gates above
  were executed separately, not inferred from a deferred marker.
- [Production Images 38522865410](https://github.com/cksidney/TibaTrace/actions/runs/38522865410):
  full migrated SQLite suite passed **2,137 tests**, with no failures, errors or
  skips; all application gates passed. Its mandatory separate PostgreSQL
  **16.15** gate also passed **2,137 tests**, with no failures, errors or skips;
  exact source/vendor/version and JUnit evidence were independently checked.
  Image publication and smoke/provenance generation passed. Both published
  image attestations were verified with the exact source digest, release tag,
  signer workflow and GitHub-hosted-runner requirement.
- The production dependency audit contains 58 resolved packages and no known
  vulnerability findings. The exact-source CI backend/HQ container scans have
  valid Linux amd64 source-linked inventories on Alpine 3.24.2 and no findings.
  Backend Python inventory contains 59 packages. No advisory allowlist,
  suppression or ignore-unfixed policy was used. Published-image scans
  were independently checked too and contain no findings. Release evidence
  SHA-256 checksums and nonempty SBOM inventories verified.
- Local rc44 non-demo SQLite: 1,943 passed, 194 deliberately deselected. This is
  a partial diagnostic result, not a full-suite gate. Earlier long-lived local
  runs started on rc43 and observed rc44's VERSION file later; their certification
  version assertion correctly failed. They are not reported as clean full runs.
  The isolated current-version SQLite assertion passed; exact-source CI
  PostgreSQL evidence above includes that assertion and all demo scenarios.

## Runtime and migration scope

Commercial B2B price-list maker/checker and exact-content publication, six
source-backed report packs, inspection-only maintenance admin, PostgreSQL
checkout/refund/stocktake/onboarding/FEFO reservation repairs, request-size
boundaries and supported dependency/runtime security repairs are included.

The only new migration is `sales.0005_commercial_quantity_breaks`. It replaces
the uniqueness constraint to include minimum quantity; it removes no rows or
columns. The removal is explicitly present in the reviewed operation inventory,
not hidden as non-destructive. Do not reverse that constraint after same-date
quantity breaks exist. Any application rollback must preserve subsequent
business facts and recheck compatibility; a dump is not authority to erase them.

Windows remains signed managed-device POS **1.0.5**. Native/shared source matches
its signed release `517183ff3025041dbf4d8d25eb36379d785fa29f`, so no new installer
is implied by rc44. Android debug validation is not a signed production release.

## Activation record

All required release gates passed. The fresh root-only PostgreSQL custom dump,
restore inventory and SHA-256 verified in
`/opt/tibatrace/backups/tibatrace-rc44-predeploy-20261014T075915Z` before migration.
Source archive SHA-256:
`97161c9539bb3a289849b7149fbae6739d9555f77418d088bfae44dabb732b77`.

Active directory:
`/opt/tibatrace/releases/tibatrace-1.0.0-rc44-19007332-20261014`.
API/HQ healthy; worker/beat running, all at runtime revision above. Migration
and Django system checks, actual PostgreSQL 16/runtime imports/version, secret
length/DEBUG policy, hourly-expiry configuration, worker ping and public HTTPS
health/HQ passed. Both expiry tasks are registered. Migration used bounded
lock/statement timeouts. No app rollback or database restore was needed.

- Authenticated HTTPS catalogue and commercial pricing options passed. All six
  new report downloads passed their row-shape/basis and audited receipt-validation
  checks. These live checks used an existing authorised account and an empty
  active tenant (zero source rows), not a populated clinical/sales acceptance
  scenario. Automated tests separately cover nonempty source facts and isolation.
- The maintenance write barrier was verified across all 103 registered models.
  The quantity-break constraint and 62 available report packs match the candidate.
  The unsupported GL export correctly remains unavailable with 501.
- HQ and native installer handoff returned 200. Anonymous clinical, retail and
  installer routes returned 401.
- Signed Windows 1.0.5 authenticated HTTPS download matched **107,955,670 bytes**
  and ZIP SHA-256
  `11b9575db8426533e24eb543ef3659f7aa36020c5e7dd846d35b5179c47bbca9`.
  No new installer was needed. Certificate enrolment and physical acceptance
  remain required; this does not claim public-CA trust or hardware certification.
- The first smoke process finished while its SSH output channel stalled. A
  bounded retry with server-side capture completed with exit 0 and all assertions;
  `/opt/tibatrace/releases/rc44-postdeploy-smoke.log` is retained. Only the stalled
  local test SSH process was stopped; production services were not stopped.

Verified immutable images:

```
ghcr.io/cksidney/tibatrace-backend@sha256:ed36678fffeceed247e917c7be41744df5ca3d795584d74dddb43088e0f199e3
ghcr.io/cksidney/tibatrace-hq-web@sha256:f8977d652cc5c1d67f8d2129efc936c271057e00049a009c4538c908e2ad9e44
```

rc37 images, directory and backups remain retained. No production stock, sale,
prescription, credential or access grant has been created for verification.
Future release migration baseline is the now-live runtime revision above.

## Remaining acceptance and business scope

- [XP-470B Windows USB labels](XP470B_WINDOWS_LABEL_ACCEPTANCE.md): device
  specifications are recorded, but actual label width/height, physical output
  and the separate receipt-printer/drawer model are unconfirmed. The current
  medicine-label renderer is text-only, not barcode-label support.
- Managers confirm actual imported stock selling/pack units, batches, expiry,
  governed quality release and installed-device/scanner/printer/drawer outcomes.
- Approved Android release signing and DHA/HWR/PPB/SHA/insurer/M-PESA onboarding
  remain pending. External provider templates stay disabled; cash-only remains
  the approved first settlement phase.
- Customer agreement/promotion/profile authoring and 38 unavailable report packs
  still require governed source contracts/workflows. The 62 available packs
  do not establish GL, profit, bank balance or regulatory certification.
- VPS and local capacity require attention: after activation approximately
  **935 MiB free / 98% used** on the VPS. No unrelated project, production
  data, prototype draft or rollback asset has been deleted or broadly pruned.

This record is release evidence, not a claim that every business workflow,
physical device or external regulatory integration has been certified.
