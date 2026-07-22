# DawaTrace Phase 1 Report

## 1. Executive Summary

The DawaTrace standalone product is architecturally feasible as a modular Django
monolith with independently packaged HQ, Windows POS and Android POS clients.
The relevant Mercato implementation is substantial and validated, but it is not
an isolated Pharmacy subtree. The operational Pharmacy service directly reaches
many mixed business apps, while clinical/FHIR behavior is split across a second
prescription model family.

Phase 1 created a non-destructive extraction foundation only. No source module was
deleted or moved, no production data or migration was touched, no artifact was
published, and nothing was deployed.

Final decision: **DAWATRACE_EXTRACTION_READY_WITH_BLOCKERS**.

Phase 2 may begin with source freeze, decisions and an independent skeleton. It
must not begin a live data cutover until the canonical healthcare model, migration,
identity, clinical-content and reconciliation blockers are closed.

## 2. Repository Findings

Audit baseline: Mercato-OS commit
`5c84ad1781d843654b4bc446466384fee18394f1`. The worktree was already heavily
dirty and included untracked Phase 7 healthcare source, so a clean signed source
tag remains mandatory.

Observed source inventory:

- 38 Django app directories
- 544 backend source files and approximately 166,845 source lines
- 261 backend migration files and 82 backend test files
- 278 HQ source files
- 39 Windows POS source files
- 29 Android POS source files
- 27 shared frontend package source files
- 138 files, approximately 17,584 lines and 19 migrations in the four immediate
  healthcare roots: Pharmacy, prescription, FHIR and pharmacy intake

The core findings are:

1. `backend/apps/pharmacy` contains the operational end-to-end workflow, including
   patient/prescriber records, DUR, prescription, FEFO, dispense, controlled stock,
   returns, recalls, labels, settlement, stock, finance and audit integration.
2. `backend/apps/prescription` contains a second patient/practitioner/prescription/
   dispense family plus normalized ingredients, clinical knowledge/plugins,
   tenant-owned clinical resources and terminology models.
3. `backend/apps/fhir` provides the measured R4 API, 19 resources, Bundle,
   OperationOutcome, terminology operations, tenant-qualified references and
   idempotency behavior.
4. `ClinicalDomainService` is a genuine invariant-enforcing command boundary. It
   validates tenant context, owned references, immutable patient links, required
   values, status transitions, chronology, transactions and idempotency. It is
   not merely indirect generic ORM persistence.
5. Pharmacy catalogue behavior is embedded in a mixed `catalog` app; required
   inventory, procurement, sales, payments, finance, reporting, sync, users and
   tenancy behavior is similarly mixed with excluded Mercato modes.
6. Windows Pharmacy POS is embedded in a multi-mode application whose main
   `App.tsx` exceeds 16,000 lines. Android also shares its application shell and
   generic offline stack with other modes.
7. Windows currently fails closed for queued offline Pharmacy sales while Android
   contains offline FEFO/deduction support. DawaTrace needs one certified policy.
8. Global Celery/beat and shared API clients include unrelated domains and cannot
   be copied wholesale.
9. Existing app migration graphs cross the intended product boundary. DawaTrace
   needs independent initial migrations and data-import crosswalks.

The detailed evidence is in `DAWATRACE_EXTRACTION_INVENTORY.md`.

## 3. Component Classification Totals

Eighty relevant component groups were classified:

| Classification | Count | Meaning |
| --- | ---: | --- |
| `MOVE_TO_DAWATRACE` | 44 | Preserve behavior/source and tests in the target boundary |
| `SHARE_AS_LIBRARY` | 3 | Use an intentionally product-neutral package with independent versioning |
| `REIMPLEMENT_AS_CONTRACT` | 18 | Preserve behavior but replace contaminated implementation with a DawaTrace port/contract |
| `KEEP_IN_MERCATO` | 3 | Mercato-specific ownership remains in the source product |
| `REMOVE_FROM_DAWATRACE` | 9 | Explicitly excluded product mode or behavior |
| `REQUIRES_DECISION` | 3 | Canonical ownership cannot be chosen safely by code inspection alone |
| **Total** | **80** | Complete audited matrix |

Each row records source path, owner, imported, database, API, event, frontend and
migration dependencies, extraction risk and recommended action in
`DAWATRACE_COMPONENT_CLASSIFICATION.md`.

## 4. Proposed DawaTrace Architecture

DawaTrace starts as one modular backend with explicit bounded contexts:

`platform`, `tenancy`, `identity`, `organizations`, `medicines`, `catalogue`,
`patients`, `practitioners`, `prescriptions`, `dispensing`, `clinical`, `cds`,
`fhir`, `terminology`, `inventory`, `batches`, `procurement`, `suppliers`,
`controlled_drugs`, `quality`, `recalls`, `finance`, `payments`, `reporting`,
`notifications`, `workflows`, `audit`, `integrations`, `pos`, and `mobile`.

Contexts own their schemas and cross boundaries through application services and
versioned contracts. FHIR is an anti-corruption layer over domain command/query
ports. POS clients never access Django model shape. PostgreSQL, Redis, queues,
object storage, secrets, domains, signing keys, application IDs and release
channels are independent from Mercato.

Microservices are not justified at extraction time. Backend, worker, beat and HQ
are separate processes around one modular monolith, which preserves transaction
integrity while boundaries are stabilized.

## 5. Pharmacy POS Architecture

The POS transaction state machine is:

```text
DRAFT -> CLINICAL_REVIEW -> BLOCKED or APPROVED -> DISPENSING
      -> READY_FOR_PAYMENT -> PAID -> DISPENSED -> REVERSED where authorized
```

Server commands enforce every transition. Prescription lines cannot move directly
from item selection to tender. Clinical findings, pharmacist overrides, per-line
FEFO/batch selection, controlled verification, payment, dispense, stock, finance,
labels, receipts and reversals retain immutable linked evidence.

The initial certified offline policy permits trusted catalogue/draft support and
approved ordinary OTC behavior only. New clinical review, clinical override,
controlled dispensing, provider payment confirmation and final prescription
dispense fail closed offline until a separate safety design certifies leases,
reservations, revocation, controlled sequence and reconciliation.

Full design: `DAWATRACE_POS_ARCHITECTURE.md`.

## 6. Drug Interaction Engine Architecture

DawaTrace consolidates the operational item-based Pharmacy DUR and normalized
Phase 7 plugin engine. It retains validated behavior but exposes one canonical
evaluation and finding contract based on normalized active ingredients, classes,
patient context and a pinned immutable knowledge release.

Rules are versioned, effective-dated, source-attributed, licensed, tenant-aware,
auditable, explainable, testable and explicitly activated. Required families cover
interactions, class rules, allergies, duplicate therapy, conditions, age,
pregnancy/breastfeeding, renal, hepatic, dose, maximum daily dose, duration,
early refill and controlled medicine controls.

Severity is `INFORMATIONAL`, `MINOR`, `MODERATE`, `MAJOR`, or `CONTRAINDICATED`.
Required knowledge/evaluator failure is explicit and fails closed for dispensing;
it is never converted to an empty safe result. Demo content remains separate from
licensed production content.

Full design: `DAWATRACE_DRUG_INTERACTION_ENGINE.md`.

## 7. Data Ownership Decisions

DawaTrace owns future healthcare and pharmacy records in its own database,
including patients, practitioners, prescriptions, dispenses, medicines,
ingredients, interactions, allergies, conditions, encounters, observations,
batches, controlled registers, clinical documents, FHIR identity/idempotency,
terminology and pharmacist overrides.

Operational Pharmacy transactions/lines in `dispensing`, tenders in `payments`,
procurement, inventory and finance source links required to complete and reconcile
a dispense also become DawaTrace-owned.
External IdPs, payment/tax authorities, EMRs and licensed content services are
accessed through adapters, while DawaTrace retains its own external IDs, evidence
and reconciliation state.

No target row has a live Mercato database foreign key. Immutable source
crosswalks and versioned events/APIs handle migration and time-boxed coexistence.
Full map: `DAWATRACE_DATA_OWNERSHIP.md`.

## 8. Extraction Sequence

The gated sequence is:

1. Freeze and sign a clean Mercato source baseline.
2. Create an independent repository and deny excluded imports.
3. Bootstrap platform, tenancy, identity, organizations, audit and workflows.
4. Extract and parity-test clinical, FHIR and terminology behavior.
5. Extract medicines/catalogue and consolidate CDS.
6. Extract inventory, batches, quality, recalls, suppliers and procurement.
7. Extract dispensing, controlled drugs and pharmacy sales.
8. Reimplement payment, finance, tax and external integration contracts.
9. Extract focused HQ, Windows POS and Android POS clients.
10. Run repeatable crosswalk-based migration and complete reconciliation.
11. Establish independent immutable CI/CD, signing and certification.
12. Pilot tenant-by-tenant with measured rollback; decommission Mercato Pharmacy
    only in a later, separately approved programme.

Full gates and rollback actions: `DAWATRACE_EXTRACTION_PLAN.md`.

## 9. Identified Blockers

Phase 2 extraction work may start, but these decisions/evidence block product
cutover:

- intended source is not yet represented by one clean tracked release tag
- canonical patient and practitioner merge rules are unapproved
- canonical prescription/line/dispense aggregate and status/ID map are unapproved
- independent migration graph and reconciliation import do not yet exist
- copied versus federated identity/coexistence strategy is unapproved
- item-based DUR and ingredient-based CDS are not yet consolidated
- several modeled CDS rule families do not yet have equivalent evaluators
- one knowledge-provider path can ambiguously return no findings when no active
  knowledge version exists
- production medicine/interaction content provider and licensing are unapproved
- Firely evidence is unavailable, so DawaTrace remains `NOT_FHIR_PORTABLE`
- one certified Windows/Android offline prescription policy does not yet exist

Thirty-eight tracked risks and their mitigation, validation and rollback are in
`DAWATRACE_EXTRACTION_RISK_REGISTER.md`.

## 10. Test Results

Validation used a disposable Python 3.11 virtual environment because the existing
`/Users/sidneykibet/venv` contained stale Django 4.2.11 and failed dependency
startup before application checks. The clean environment resolved and verified:

```text
Django                  5.1.15
fhir.resources          6.5.0
pydantic                1.10.26
pip check               pass
```

### Django and migrations

| Command | Result |
| --- | --- |
| `python backend/manage.py check --settings=rms.test_settings` | Pass, no issues |
| `python backend/manage.py makemigrations --check --dry-run --settings=rms.test_settings` with isolated SQLite test DB | Pass, no changes detected |

### Focused backend suites

| Scope | Exact result |
| --- | ---: |
| Pharmacy, batches, hardening, intake, catalogue import/demo and catalogue governance | 84 passed |
| Prescription package, including CDS engine tests | 24 passed |
| Phase 7.1/7.2/7.2.2 FHIR, terminology and clinical round-trip suites | 177 passed |
| Pharmacy-used inventory, procurement, payments, finance, tax, shifts, reversals and receipts | 232 passed |
| RBAC, tenancy, multitenancy, hardening, password, production security and module access | 91 passed |
| **Focused backend total** | **608 passed, 0 failed** |

The backend suites emitted deprecation/configuration warnings, principally the
missing test `staticfiles` directory and a DRF converter warning for Django 6.
They did not produce test failures.

### Frontend and POS

| Command/scope | Result |
| --- | --- |
| Windows POS TypeScript check, version 0.1.124 | Pass |
| Android POS TypeScript check, version 0.1.71 | Pass |
| HQ TypeScript check, version 0.1.0 | Pass |
| Shared package TypeScript check | Pass |
| Nine focused Pharmacy/FEFO/POS/offline/label/receipt/session Node test files | 51 passed, 0 failed |

The first Node invocation loaded 46 tests but one test file could not load because
the ignored `packages/brand/dist` prerequisite had not been built. After building
the brand and shared workspaces, the same intended suite was rerun and all 51
tests passed. No generated build output was added to the Phase 1 changes.

This pass did not rerun the complete 1,200-test backend baseline, HQ production
build, installer/APK packaging, Firely suite, deployment or production smoke tests.
Those are not claimed as Phase 1 results.

## 11. Files Created or Changed

Only these Phase 1 documents were intentionally added:

1. `docs/dawatrace/DAWATRACE_PRODUCT_ARCHITECTURE.md`
2. `docs/dawatrace/DAWATRACE_EXTRACTION_INVENTORY.md`
3. `docs/dawatrace/DAWATRACE_COMPONENT_CLASSIFICATION.md`
4. `docs/dawatrace/DAWATRACE_DATA_OWNERSHIP.md`
5. `docs/dawatrace/DAWATRACE_POS_ARCHITECTURE.md`
6. `docs/dawatrace/DAWATRACE_DRUG_INTERACTION_ENGINE.md`
7. `docs/dawatrace/DAWATRACE_EXTRACTION_PLAN.md`
8. `docs/dawatrace/DAWATRACE_EXTRACTION_RISK_REGISTER.md`
9. `docs/dawatrace/DAWATRACE_PHASE_1_REPORT.md`

No application source, dependency lock, migration, production configuration or
deployment file was intentionally changed by this phase.

## 12. Decisions Requiring Approval

1. Choose the canonical patient, practitioner, prescription and dispense models,
   including source-ID, status, quantity and FHIR-reference mappings.
2. Choose identity migration: copied local users, OIDC federation or staged hybrid.
3. Choose the global medicine, terminology and clinical-content providers and
   approve licence, jurisdiction and promotion governance.
4. Choose tax/eTims system-of-record ownership and credentials for DawaTrace.
5. Choose tenant cutover/coexistence duration and permitted event directions.
6. Approve retention, residency, PHI export and controlled-record policies.
7. Approve the initial fail-closed offline prescription policy and any future
   clinical offline certification scope.
8. Name accountable clinical safety, security, migration, finance and release owners.

## 13. Recommended Phase 2 Execution Plan

The next programme increment should be limited to:

1. commit, review and tag the exact intended source baseline
2. approve the eight decisions above as architecture records
3. create the private DawaTrace repository with independent infrastructure and
   forbidden-import CI
4. bootstrap tenancy, identity, organizations, audit and contract packages
5. copy the clinical/FHIR core with unchanged behavior and tests
6. design independent initial migrations and dry-run crosswalk import tooling
7. rerun the full 1,200 backend baseline plus focused client/FHIR evidence from a
   clean immutable build environment

Do not copy the mixed Pharmacy, sales, inventory, catalogue or POS shells wholesale
and call the result standalone. Operational contexts should move only after their
contract and reconciliation gates exist.

## Final Phase Decision

**DAWATRACE_EXTRACTION_READY_WITH_BLOCKERS**
