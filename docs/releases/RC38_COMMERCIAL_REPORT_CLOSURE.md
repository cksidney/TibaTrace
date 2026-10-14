# rc38 candidate — commercial pricing and source reports

This is a candidate record, not confirmation of live deployment.

## Implemented scope

- HQ B2B draft maintenance, cloning, independent review, publication and explicit
  archive. Current contents are hashed and recorded in the append-only event
  journal. Contributors cannot approve; stale decisions and revoked approvers
  cannot publish. No live price or history deletion through generic CRUD.
- Retry-bound HQ draft create/update and governance commands. Cross-tenant
  entries, non-positive prices, expired-only/empty drafts, overlapping equal
  quantity breaks, conflicting active defaults and currency mismatches refused.
- Sales migration 0005 changes only the entry uniqueness constraint to include
  minimum quantity: genuine quantity breaks can share a start date. Existing
  rows are preserved. Do not reverse this constraint after same-date breaks are
  created without checking compatibility; application rollback is distinct from
  database reversal.
- Six report routes backed by actual source records: commercial order cohorts,
  customer creation cohorts, authorised patient medication supply history,
  observed operator activity, open-till cash projections and FHIR idempotency
  observations. Sensitive sources need corresponding domain capabilities;
  branch-scoped actors remain scoped. Contact details, patient narratives and
  idempotency keys/hashes are not exported. Downloads retain access receipts.
- 62 of 100 report packs are source-backed; 38 remain explicitly unavailable.
  Names and bases do not claim revenue, posted accounting, human productivity
  rankings, regulator acceptance or a physical counted-cash balance.

## Validation and release gates

Local HQ typecheck/build and 68 tests passed before final release packaging.
Focused backend and full clean-checkout SQLite/PostgreSQL, workspace, migration,
immutable image/provenance and VPS gates must pass before activation. Deployment
details will be recorded separately after actual success.

Windows remains the validated signed managed-device release 1.0.5. This candidate
does not change Windows/Android source or imply a new installer was published.
Android signing and Managers' actual stock and USB printer/scanner/drawer
acceptance remain outstanding. External integrations remain disabled templates.
Customer agreement/promotion governance and unsupported ledgers/report sources
remain separate open work. Untracked prototypes and user artifacts are excluded.

VPS last observed 97% used with about 1.4 GiB free. No unrelated project pruning,
data deletion or removal of required rollback material is authorised by this
candidate release.
