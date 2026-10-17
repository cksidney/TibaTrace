# TibaTrace business logic and workflow audit — 13 October 2026

Local diagnostic report. Not a certification, not a deployment, and not published
to GitHub. No application code or production data was changed during this audit.

## Verdict

**The deployed system is healthy, but full business workflows are not complete.**
There are confirmed authorization and state-integrity defects, incomplete
operator journeys, incomplete reporting, and separate operational acceptance
blockers. Passing the release suite does not establish complete business coverage.

Repository and live HQ/API/worker/beat match rc33, commit
`228a3325ec84dc6eaae11ef0ed06c55dcf6707eb`. Remote references were refreshed.
The existing local Stage 2D.2 prototype remains untracked and undeployed.

## Method and evidence

- Inspected HQ, Windows POS, Android POS, legacy web POS, shared clients, backend
  domain services, API permissions/actions, reporting and job configuration.
- Read live version/health metadata and aggregate readiness counts. Live database
  inspection ran inside a PostgreSQL `SET TRANSACTION READ ONLY` transaction.
- Re-ran 59 existing control tests: dispensing, retail, activation, pricing,
  reports, procurement, clinical intake and stocktake. All passed.
- Eight additional local diagnostic probes passed by reproducing seven current
  gaps and confirming one cross-tenant denial. These assertions document current
  symptoms; they are **not** assertions that the defective behavior is acceptable.
- Probes used a disposable local clone and synthetic records, never live sales,
  patients, refunds or stock. Evidence:
  `/private/tmp/tibatrace-surface-audit.vK2mSs/audit-probes.xml` and
  `/private/tmp/tibatrace-surface-audit.vK2mSs/existing-control-tests.xml`.
- Yesterday's full rc33 release suite (1,923 backend + 400 application/shared
  tests) remains a source-matched baseline, not a new exhaustive audit run.
- Hardware and real-provider acceptance were not performed. UI findings below
  are code/contract findings, not a claim that every screen was exercised with
  a live authenticated operator. Older audit documents contain superseded claims.

## Surface coverage

| Surface | Controls that exist | Material remaining gaps |
| --- | --- | --- |
| HQ tenant/platform administration | Tenant lifecycle, users/roles, forced password change, independent activation review | Read-permission consistency; complete operational onboarding; action queues/pagination |
| HQ catalogue/pricing/initial setup | Source import/review, SKU draft intake, catalogue activation, governed price drafts/approval/publication | Source-to-saleable-stock orchestration, branch assortment provisioning and manager acceptance |
| HQ procurement/inventory | Requisitions/orders/receipts, quality decisions, transfer modal/workflow, stocktake writes | Recount/cancellation/complete-count exception paths; scheduled expiry projection maintenance |
| HQ commerce/clinical | Actions on existing quotations/orders/dispatches/returns and prescriptions; clinical data intake | Creation and full fulfilment/Rx-to-dispensing journeys; stale and bounded collections |
| Windows POS | Activation, register/shift context, retail cash settlement, clinical screening, counselling/collection services | Generic terminal-state bypass; clinical preparation/final-check wiring; completed-sale refunds; hardware transport |
| Android POS source | Shared retail/clinical clients, secure storage and activation | Same clinical gaps; release signing and installed-device acceptance still pending |
| Legacy web POS `/pos/` | Served by backend; HQ still links to it | Broken batch action path, old clinical orchestration, no native activation-proof propagation |
| API | Tenant scoping and many guarded mutation services | Missing read capabilities on several POS/financial surfaces; generic status endpoint bypasses authoritative facts |
| Reports/finance/audit | 17 validated HQ report queries; separate current-state compliance packs; till cash reconciliation | 83 unavailable HQ packs; retail collections absent from sales-period export; identity changes omitted from permission report |
| Integrations/regulatory/jobs | Templates, approval states, credential references, manual recall holds/releases, event worker | No active provider endpoints/feeds; no configured periodic beat tasks; external and hardware acceptance absent |

## Prioritized findings

### F01 — P1: terminal dispensing states can bypass authoritative facts

`PosDispensingQueueService.transition_state` requires only `dispensing.prepare`.
It permits `READY_FOR_SUPPLY → SUPPLIED`, `READY_FOR_PAYMENT → PAID` and terminal
closure through a generic assignment. Its additional clinical checks apply only
when entering READY_FOR_PAYMENT/READY_FOR_SUPPLY, not when entering SUPPLIED.

Confirmed locally through the actual transition-state API: a user with only
`dispensing.prepare`, and no supply capability, changed a ready episode to
SUPPLIED while **no MedicineSupply record existed**. This does not prove that
stock was physically issued; it proves that status/history can falsely claim
completion without the authoritative supply service and its inventory facts.

Fix direction: terminal payment/supply/reversal/closure projections must be
owned by their canonical services. A generic transition must not manufacture
them. Add negative tests for preparer-only users and missing financial/stock facts.

Evidence: [transition service](/Users/sidneykibet/TibaTrace/backend/apps/prescription/pos_dispensing_services.py:77),
[API action](/Users/sidneykibet/TibaTrace/backend/apps/prescription/pos_dispensing_api/views.py:93).

### F02 — P1: authentication alone permits sensitive same-tenant reads

The native dispensing viewset uses IsAuthenticated and tenant filtering, but no
clinical read capability. A newly created tenant user with **zero capabilities**
received HTTP 200 for both an episode and its queue, including patient identity,
date of birth and a recorded allergy reaction. The same kind of user retrieved
a completed retail transaction and its cash receipt amount.

Cross-tenant header access was correctly refused with HTTP 403. This finding is
missing role/minimum-necessary authorization **within a tenant**, not a claim
that arbitrary users can read other tenants or that anonymous access succeeds.
Payment and pricing read-only viewsets show the same IsAuthenticated-only pattern
and should be included in the remediation review.

Fix direction: enforce read capabilities, branch/device scope where required,
and role-aware clinical redaction. Test no-role, cashier, pharmacist, manager,
platform and suspended identities separately. Cashier privacy differs from
pharmacist privacy in the repository's own policy.

Evidence: [POS read permission](/Users/sidneykibet/TibaTrace/backend/apps/prescription/pos_dispensing_api/views.py:58),
[allergy serializer](/Users/sidneykibet/TibaTrace/backend/apps/prescription/pos_dispensing_api/serializers.py:192),
[retail queryset](/Users/sidneykibet/TibaTrace/backend/apps/pos_transactions/api/views.py:65),
[privacy policy](/Users/sidneykibet/TibaTrace/docs/domain/POS_PATIENT_PRIVACY.md:1).

### F03 — P1: native clinical journey does not record its advertised final check

Both Windows and Android “Complete final check” controls POST
`new_status: CHECKING` to the compatibility status endpoint. That changes the
episode status; it does not call DispensingCheckService or create a passed
independent check. The local probe confirmed the absence of a check record.
The genuine downstream payment/supply services correctly require that record,
so the supported operator journey cannot progress by merely pressing this button.

Shared/native clients do not expose the complete canonical reserve → allocate →
prepare → independent check workflow. HQ supports review of existing prescriptions,
but a complete manual Rx/episode creation-to-supply operator journey is not wired
across these surfaces. API functionality is not the same as an usable till journey.
Native medicine headings/comparisons also render SKU identifiers from the current
DTO rather than readable medicine/pack descriptions.

Fix direction: wire the canonical actions, independent actor/checklist evidence,
real item context, partial/substitution paths and error/unknown-outcome handling.
Do not relax the backend check to make the buttons appear successful.

Evidence: [Windows command](/Users/sidneykibet/TibaTrace/apps/pos-windows/src/components/tibatrace/PrescriptionWorkspace.tsx:113),
[Android command](/Users/sidneykibet/TibaTrace/apps/pos-android/src/screens/DispensingScreen.tsx:207),
[canonical check API](/Users/sidneykibet/TibaTrace/backend/apps/prescription/api/views.py:675).

### F04 — P1 workflow coverage: completed retail sales have no refund/return path

Retail cash settlement, stock issue and immutable receipts are implemented.
There is no retail refund/reversal action on the transaction viewset. Cancellation
correctly refuses a completed sale; the local probe confirmed this after a real
synthetic cash settlement. Clinical payment reversal and wholesale sales returns
are separate models and do not close this retail receipt journey.

Required closure: supervisor approval, original receipt/line linkage, refund money
fact, stock return custody/quality disposition, till adjustment, receipt and
idempotent replay. Never refund by deleting a receipt or cancelling a paid cart.

Evidence: [retail actions](/Users/sidneykibet/TibaTrace/backend/apps/pos_transactions/api/views.py:185),
[unpaid cancellation restriction](/Users/sidneykibet/TibaTrace/backend/apps/pos_transactions/services.py:721).

### F05 — P1 reporting coverage: retail cash is absent from sales-period exports

The sales-period/branch queries read dispensing PaymentSettlement records only.
A completed synthetic retail sale produced a KES 250 RetailCashReceipt, while
the sales-period report returned zero rows. Till cash reconciliation separately
includes retail receipts, so the two surfaces have different coverage.

The existing export explicitly describes dispensing collections; its arithmetic
is not being called fraudulent. The gap is the absence of a complete retail-plus-
clinical collection/reporting contract for the business. Accrual revenue, VAT,
profit and receivables must also remain distinct from settled collections.

Evidence: [collection query](/Users/sidneykibet/TibaTrace/backend/apps/platform/reporting/queries.py:64),
[retail receipt creation](/Users/sidneykibet/TibaTrace/backend/apps/pos_transactions/services.py:577),
[till aggregation](/Users/sidneykibet/TibaTrace/backend/apps/pos_shift/cash_control.py:158).

### F06 — P1 onboarding completion: source review does not make goods tradeable

Initial setup preserves source rows and manager evidence, always returning
`saleable: false`. A separate SKU draft intake and activation path exists, but
there is no linked, batchable source-review → governed product/pack mapping →
assortment → approved price → opening stock/quality release completion journey.
The branch-assortment API is read-only. The audit did not find a supported HQ
branch-assortment provisioning control. Manager review alone cannot create stock.

Live TransElgon counts confirm that this is still an incomplete setup, not a
tenant ready to trade. Preserve the safety boundary: never infer units, licence
status, batches or expiry, or make source quantities saleable just to clear it.

Evidence: [non-saleable review response](/Users/sidneykibet/TibaTrace/backend/apps/medicines/api/onboarding.py:53),
[review persistence](/Users/sidneykibet/TibaTrace/backend/apps/medicines/onboarding.py:65),
[assortment surface](/Users/sidneykibet/TibaTrace/backend/apps/medicines/api/views.py:349).

### F07 — P2: permission-change report omits actual identity audit events

The permission-change report filters model names matching
`identity|tenant|configuration`. User administration writes `model_name="User"`;
the rc33 role reconciliation also writes `Role`. The local probe stored an actual-
format IDENTITY_USER_ROLES_UPDATED event and confirmed that the report omitted it.
The audit record exists; the specialized report selection is wrong.

Fix direction: use a canonical model/action taxonomy and regression tests that
generate events through the real identity administration endpoints.

Evidence: [identity event format](/Users/sidneykibet/TibaTrace/backend/apps/identity/api/views.py:116),
[report filter](/Users/sidneykibet/TibaTrace/backend/apps/platform/reporting/queries.py:109).

### F08 — P2/full-scope gap: 83 of 100 HQ report packs remain unavailable

Only 17 catalogue IDs belong to the validated AVAILABLE set. The remaining 83
are intentionally unavailable/501 rather than fake successful downloads. Missing
packs span accounting/GL/AP/AR/VAT/profit, procurement, controlled-drug registers,
clinical and regulatory reporting, and operational analyses. Six separate
current-state compliance report types do not implement these 83 catalogue packs.

Set a phase-one required report list, implement and reconcile its real source
queries, and keep the remaining packs honestly marked planned. Full accounting
and regulatory/reporting completeness cannot currently be claimed.

Evidence: [availability set](/Users/sidneykibet/TibaTrace/backend/apps/platform/reporting/queries.py:12).

### F09 — P2: HQ commerce has existing-record actions, not a complete journey

Quotation/order approval, reservation/allocation, dispatch and return controls
exist in the generic BusinessWorkbench. They must not be described as absent.
However, the HQ surface lacks the complete creation/line editing and picking-wave,
packing and proof-of-delivery journey. Several fulfilment tabs are monitoring
tables over backend services rather than operator execution controls.

Evidence: [commerce workbench](/Users/sidneykibet/TibaTrace/apps/hq-web/src/App.tsx:8173),
[existing-record actions](/Users/sidneykibet/TibaTrace/backend/apps/platform/admin_shell.py:1460),
[collection-only fulfilment clients](/Users/sidneykibet/TibaTrace/apps/hq-web/src/api.ts:3443).

### F10 — P2: bounded and stale HQ collections can hide or misstate work

BusinessWorkbench queues are capped at 50 records and its search filters only
those returned rows. Generic collection helpers discard pagination metadata.
The commerce supplementary tables load only on mount (`useEffect(..., [])`),
not after an action refresh or operating-tenant change. This can leave tables
stale or associated with the previously selected tenant. It is not proof of a
cross-tenant mutation bypass; the backend tenant boundaries remain relevant.

Required closure: server-side paging/search, explicit total/partial indicators,
tenant/refresh dependencies, stale-state clearing and visible load failures.

Evidence: [50-row limit](/Users/sidneykibet/TibaTrace/backend/apps/platform/admin_shell.py:1107),
[local-only search](/Users/sidneykibet/TibaTrace/apps/hq-web/src/App.tsx:9928),
[stale effect](/Users/sidneykibet/TibaTrace/apps/hq-web/src/App.tsx:8158),
[pagination discard](/Users/sidneykibet/TibaTrace/apps/hq-web/src/api.ts:619).

### F11 — P1 for legacy users: the linked web POS has obsolete contracts

HQ still links to `/pos/`, and the deployment routes it to the Django backend.
Its batch application calls `/episodes/<id>/verify-batch/`, while the registered
API is the collection action `/episodes/verify-batch/` and requires a SKU ID.
Resolver inspection confirmed the legacy detail route is not registered (404).
The web UI also uses status transitions as its pharmacist-check command and
does not propagate the signed native activation proof required for non-demo
production dispensing mutations.

Decision required: retire this third surface from navigation/support or bring it
onto the same current contracts and controls. Do not leave a broken “Point of sale”
shortcut in HQ while certifying only the two native implementations.

Evidence: [bad batch call](/Users/sidneykibet/TibaTrace/backend/static/pos/js/pos.js:1192),
[web request headers](/Users/sidneykibet/TibaTrace/backend/static/pos/js/pos.js:45),
[served route](/Users/sidneykibet/TibaTrace/deploy/tibatrace/Caddyfile:11).

### F12 — P2: stocktake exception/completeness paths are incomplete

Counts and independent variance approval exist. Duplicate counts are rejected,
and the UI tells the operator to choose another item. There is no supported
recount/correction or session cancellation action, and posting checks at least one
count but does not enforce complete location/SKU coverage for a FULL session.
These are source-inspected workflow gaps, not a claim of a live stock corruption.

Evidence: [stocktake service](/Users/sidneykibet/TibaTrace/backend/apps/inventory/services.py:1141),
[posting conditions](/Users/sidneykibet/TibaTrace/backend/apps/inventory/services.py:1201),
[duplicate-count UI](/Users/sidneykibet/TibaTrace/apps/hq-web/src/App.tsx:2143).

### F13 — P2: periodic inventory maintenance is not configured

The deployed CELERY_BEAT_SCHEDULE is empty. ExpiryControlService exists, but no
production call/scheduled task was found to run it periodically. Event-driven
worker jobs are a separate mechanism and are not thereby claimed to be broken.
Retail's current-date expiry guard exists and its regression test passed; that
does not update every stock projection, expiry alert or management snapshot.

Evidence: [empty schedule](/Users/sidneykibet/TibaTrace/backend/dawatrace/settings/base.py:245),
[expiry projection service](/Users/sidneykibet/TibaTrace/backend/apps/inventory/services.py:1251).

## Live readiness snapshot

| Aggregate | Nairobi Chemists | TransElgon Apex Pharmacy |
| --- | ---: | ---: |
| Tenant mode | Demo | Non-demo |
| Tenant status | ACTIVE | ACTIVE |
| Users | 19 | 2 |
| Active users requiring first password change | 19 | 2 |
| Imported source items | 0 | 686 |
| Source items awaiting Manager review | 0 | 686 |
| Details-complete source items | 0 | 0 |
| Active governed SKUs | 0 | 0 |
| Sellable assortment records | 0 | 0 |
| Active price-version records | 0 | 0 |
| Positive available inventory rows | 0 | 0 |
| Prescriptions / medicine supplies | 0 / 0 | 0 / 0 |
| Retail transactions / cash receipts | 0 / 0 | 0 / 0 |
| Activated devices | 0 | 0 |

These are aggregate observations, not fabricated patient/stock data. Password
change is an expected security step, not a defect to bypass. No active national/
provider configurations or active endpoints were found; periodic task names are
empty. Legacy quantities are source-review quantities, not available inventory.

## Known deferred acceptance — not misclassified as newly discovered bugs

- DHA/HWR/PPB/SHA/M-PESA remain templates, as previously approved. Real licence
  lookup, regulator push feeds, eligibility/claims and payment-provider acceptance
  cannot be claimed. Approved contracts/endpoints and real adapter validation are
  still needed. Manual internal verification is not national verification.
- Android release signing is still absent from GitHub. The protected
  `android-release` environment is absent; only Windows signing-secret names
  exist. Preserve the approved Android signing identity; never substitute an
  unsigned/debug-signed release.
- Native print controls currently drive the simulator; a reprint explicitly
  requests SIMULATOR. Hardware-specific receipt/label/drawer transport and real
  scanner/printer/device acceptance remain incomplete, not merely certified by
  passing source tests. Managers own physical acceptance.
- Retail settlement is cash-only with internal non-fiscal receipts. Clinical
  tender options separately offer explicitly labelled manual card approval.
  This policy difference should be reviewed; it is not card-terminal integration.
- Stage 2D.2 prototype/certification drafts remain excluded. Their statements
  are not accepted as operational, payment, dispensing or regulatory evidence.

## Closure order

1. Fix F01/F02 first: authoritative state integrity and minimum-necessary reads.
   Add negative regression tests before enabling real tenant activity.
2. Complete the canonical clinical workflow and resolve the legacy web POS
   support decision. Demonstrate intake-to-stock-issue/receipt with distinct
   authorized actors, refusals, timeout recovery and idempotent replay.
3. Complete the reviewed source-to-governed-stock pipeline. Managers confirm
   units, packs, batches/expiry and physical counts; then independently approve
   products/prices/quality, enrol tills and complete first-password changes.
4. Add retail refund/return money-and-stock linkage and reconcile retail plus
   clinical collections with till X/Z, source reports and audit reports.
5. Finish required commerce/reporting/stocktake exception journeys, pagination,
   refresh behavior and scheduled inventory maintenance.
6. Managers complete hardware acceptance and signing; provider integrations stay
   blocked until approved onboarding and external acceptance are available.

No fixes, account changes, live test transactions, migrations, deployments,
cleanup or repository pruning were performed as part of this diagnostic pass.
