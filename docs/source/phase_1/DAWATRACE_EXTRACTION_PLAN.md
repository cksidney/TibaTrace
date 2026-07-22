# DawaTrace Staged Extraction Plan

## Objective

Create an independently developed, tested, versioned, built, deployed, scanned,
certified, licensed and branded DawaTrace product without deleting or destabilizing
Mercato-OS. The sequence favors reproducible copying and contract replacement over
a one-time rewrite.

## Preconditions

Phase 2 execution starts only when:

- the source release is committed and tagged; the currently audited worktree is
  heavily dirty and contains untracked healthcare/FHIR source
- canonical patient, practitioner, prescription and dispense ownership is approved
- identity migration/coexistence strategy is approved
- production clinical content ownership and licensing have named approvers
- initial customer migration pattern and rollback period are approved
- accountable engineering, clinical, security and data-migration owners are named

The audit baseline is commit `5c84ad1781d843654b4bc446466384fee18394f1`, but
that commit alone does not include every untracked file inspected in Phase 1. A
clean release tag and manifest are therefore a hard extraction gate.

## Stage 0: Freeze and Evidence Manifest

1. Put all intended source on a reviewable Mercato release branch.
2. Record commit, submodule/package locks, Python and Node runtimes, container
   digests, database engine, generated schemas and artifact checksums.
3. Run the complete baseline, including the 1,200-test backend evidence target,
   Pharmacy POS tests, FHIR R4/HAPI suite and migration drift check.
4. Export a machine-readable inventory of files selected by the classification
   matrix and a denylist of excluded domains.
5. Tag the immutable source baseline. No production data is copied in this stage.

Exit gate: clean source tag, green baseline and signed extraction manifest.
Rollback: none required; Mercato remains unchanged.

## Stage 1: Create the Standalone Repository

1. Create a private `dawatrace` repository with protected default branch.
2. Preserve relevant path history with `git filter-repo` or a subtree-based import
   from the approved tag where practical. Record every filter rule.
3. Create the modular-monolith repository shape defined in the architecture.
4. Add DawaTrace-owned CODEOWNERS, security policy, release policy, threat model,
   licence manifest and architecture decision records.
5. Add an automated forbidden-import check for Restaurant, Retail, Wholesale,
   Forecourt, Factory, OMS, loyalty and Mercato deployment modules.

Exit gate: repository builds an empty backend/client skeleton from a clean clone.
Rollback: delete the new non-production repository; Mercato history is untouched.

## Stage 2: Bootstrap Platform Foundations

Copy behavior, tests and narrowly required implementation for:

- settings/health/observability
- strict tenant context and tenant-owned base models
- authentication, users, roles, capabilities and approval evidence
- pharmacy organizations, stores, registers and devices
- audit, document numbering, event/outbox and notification primitives

Reimplement contaminated `common`, `tenancy`, `users`, `sync`, `documents` and
`events` surfaces behind DawaTrace contracts rather than copying whole apps. Use
new package names, settings modules and app labels. Establish separate PostgreSQL,
Redis, object storage and secret namespaces from the first executable build.

Exit gate: tenant-isolation, RBAC, auth, audit, outbox and platform tests pass with
no excluded app in `INSTALLED_APPS`, import graph or migration graph.
Rollback: reset only the DawaTrace bootstrap branch to the Stage 1 tag.

## Stage 3: Extract Clinical and FHIR Core

1. Copy Phase 7 clinical/FHIR behavior and tests into `patients`, `practitioners`,
   `prescriptions`, `clinical`, `fhir` and `terminology` target contexts.
2. Preserve exact runtime locks `fhir.resources==6.5.0` and
   `pydantic>=1.10,<2.0`; pin the resolved Pydantic version in the lockfile.
3. Preserve `ClinicalDomainService` invariants while moving persistence behind
   context-owned repositories.
4. Implement the approved canonical patient/practitioner/prescription crosswalk.
5. Keep FHIR converters as an anti-corruption layer, not domain model ownership.
6. Re-run resource, search, write, Bundle, OperationOutcome, terminology,
   security, tenant and HAPI R4 round-trip evidence.

Exit gate: all measured 19 resources retain behavior, Bundle semantics remain
atomic/independent as appropriate, and no `FHIR_PORTABLE` claim is made without
Firely evidence.
Rollback: retain the Stage 2 tag and continue serving Mercato clinical traffic.

## Stage 4: Extract Medicines, Catalogue and CDS

1. Copy national medicine, tenant/store medicine, barcode, ingredient and
   catalogue-governance behavior without general Item restaurant/retail fields.
2. Import existing pharmacy Item identities through immutable crosswalks.
3. Consolidate item-based Pharmacy DUR and ingredient-based Phase 7 CDS behind
   one evaluation/finding contract.
4. Implement all required rule families or explicitly mark them unavailable.
5. Create signed content-release import, validation, activation and rollback.
6. Keep demo content isolated and visibly non-production.

Exit gate: catalogue reconciliation and CDS compatibility tests pass; licensed
production content and clinical governance are approved before production use.
Rollback: deactivate the candidate knowledge release and use the prior signed
release; Mercato remains the source during extraction.

## Stage 5: Extract Inventory, Batches, Quality and Procurement

Build context-owned schemas for catalogue activation, inventory ledger, balances,
locations/bins, batches, FEFO, quarantine, returns, write-offs, recalls, suppliers,
POs and GRNs. Port only pharmacy-required behavior from contaminated apps.

Replace direct foreign keys across contexts with stable IDs and application
services where needed. A received GRN emits a stock-received fact consumed
idempotently by inventory and controlled-drug registers. Rebuild projections from
ledger events and compare them with source balances.

Exit gate: receipt-to-batch-to-FEFO-to-dispense, return/quarantine, recall,
write-off, stock take and transfer suites pass, including concurrency and tenant
isolation. Every source quantity reconciles.
Rollback: stop imports, discard the non-production target database and rerun from
the immutable source snapshot.

## Stage 6: Extract Dispensing, Controlled Drugs and Sales

1. Adapt the current operational Pharmacy prescription/dispense workflow onto the
   approved canonical aggregates.
2. Implement the POS state transitions and clinical-review fingerprint.
3. Port labels, receipt linkage, refill and pharmacist/FEFO override evidence.
4. Port controlled receipt, dispense, return, write-off and reversal register facts.
5. Create DawaTrace-owned pharmacy transaction/line records in `dispensing` and
   tender records in `payments`, with reversal source documents, instead of
   importing the full mixed Mercato sales app.

Exit gate: one prescription can traverse clinical review, FEFO allocation,
payment and dispense exactly once; skipped clinical review and unsafe batches are
blocked; controlled balances reconcile.
Rollback: no live routing changes; reset to Stage 5 tag and continue in Mercato.

## Stage 7: Extract Payments, Finance and Integrations

Reimplement source-document contracts for:

- cash, M-Pesa, card, wallet and split tender
- provider confirmation, clearing and settlement reconciliation
- refunds and reversal
- account mappings, balanced journals, COGS when cost exists and procurement/AP
- tax/eTims and external accounting adapters where approved

Accounts resolve through mappings and invalid/missing mappings block posting.
External settlement is never inferred. Provider and signing credentials are newly
issued for DawaTrace and never copied from Mercato source files or databases.

Exit gate: idempotency, balancing, reversal, missing mapping, settlement,
tenant/store scope and reconciliation tests pass. Accounting and tax owners sign
the parallel-run comparison.
Rollback: keep adapters disabled and preserve the previous stage database.

## Stage 8: Extract HQ and Reporting

Copy pharmacy/clinical/FHIR pages and shared UI primitives into a DawaTrace HQ.
Replace broad `packages/shared/src/api.ts` calls with generated or typed DawaTrace
contracts. Add pharmacy inventory, procurement, finance, controlled, quality,
recall, audit and clinical reports from context-owned read models.

Remove all excluded navigation, route guards, role labels, mode selectors, copy
and assets. Reports containing PHI or controlled data require capabilities,
purpose-appropriate logging and export retention controls.

Exit gate: route inventory, keyboard/accessibility, responsive screenshot, RBAC,
tenant isolation, export and HQ production-build checks pass.
Rollback: HQ is not published until a signed release candidate passes.

## Stage 9: Extract Windows and Android POS

1. Create shared `contracts` and `pos-core` packages from validated pharmacy helpers.
2. Build focused Windows and Android shells with new application IDs, deep links,
   storage paths, icons, signing identities and update channels.
3. Implement the documented state machine and certified offline policy.
4. Verify scanner, printer, cash drawer, card/fingerprint approval evidence and
   label/receipt behavior on supported hardware.
5. Migrate no local Mercato POS database in place without a versioned, encrypted
   migration and rollback test; fresh reprovisioning is the default safer path.

Exit gate: typecheck, unit/integration/E2E, offline conflict, hardware matrix,
signed installer/APK, malware/SBOM and update/rollback tests pass.
Rollback: keep Mercato POS installed and provisioned until terminal acceptance;
support side-by-side package IDs during controlled pilot.

## Stage 10: Independent Data Migration

Build repeatable, resumable import jobs with source snapshots and immutable
crosswalks. Sequence data as:

1. tenant, organization, store and identity mappings
2. medicine, ingredient, terminology and catalogue masters
3. patients and practitioners
4. suppliers, procurement, batches and inventory ledger
5. prescriptions, reviews, dispenses and clinical records
6. controlled register, recalls, returns and quality records
7. sales, payments, finance, audit, FHIR identity and idempotency
8. open workflows/outbox records only after side-effect classification

Run dry-run, validation-only and commit modes. Every tenant receives count,
checksum, foreign-reference, balance and exception reports. A mismatch blocks
cutover; there is no best-effort silent skip.

Exit gate: two repeat runs produce identical accepted results and all ownership
reconciliation checks pass.
Rollback: restore the target snapshot or recreate it from the source snapshot;
source remains authoritative until tenant acceptance.

## Stage 11: Independent CI/CD and Immutable Builds

The pipeline must:

- install from locked dependencies in clean workers
- run forbidden-import, secret, licence, SAST, dependency and container scans
- run backend, HQ, Windows, Android, FHIR/HAPI and migration-from-zero suites
- generate OpenAPI/contracts and reject unreviewed drift
- build images and client packages once, attach SBOM/provenance/checksums, sign them,
  and promote the same digest between environments
- use DawaTrace-owned registry, domains, deployment accounts and release keys
- make migrations a reviewed deployment step with preflight and rollback evidence

Exit gate: a clean clone produces byte/reproducibility-accounted artifacts, and
the release can be rolled back without rebuilding.

## Stage 12: Certification and Controlled Pilot

1. Run security, privacy, clinical safety, penetration and disaster-recovery gates.
2. Run HAPI R4 certification using pinned images and exact evidence manifests.
3. Prepare and execute Firely testing; portability remains unclaimed until it passes.
4. Validate licensed CDS content with accountable clinical reviewers.
5. Pilot one non-critical/demo tenant, then one approved live tenant with parallel
   reconciliation and staffed rollback window.
6. Freeze writes briefly at cutover, run final delta, reconcile, switch routing,
   monitor and obtain signed acceptance.

Rollback triggers include reconciliation variance, tenant leak, clinical false
pass, duplicate dispense/payment/stock event, FHIR identity break, unavailable
statutory output, or an unrecoverable POS sync fault. Rollback restores Mercato
routing and preserves DawaTrace evidence for diagnosis; it never attempts to
erase already issued clinical or financial facts.

## Stage 13: Mercato Decommissioning

Only after every tenant passes the approved retention/coexistence period:

- disable new Pharmacy writes in Mercato
- preserve required read-only statutory history
- reconcile and drain outboxes
- revoke old device/provider credentials
- remove Pharmacy code from Mercato under a separate reviewed programme

This stage is explicitly outside Phase 1 and is not implied by creating DawaTrace.

## Phase 2 Recommended Work Packages

| Order | Work package | Primary output |
| ---: | --- | --- |
| 1 | Source freeze and decisions | clean tag, manifests and ADRs |
| 2 | Repository/platform bootstrap | independent green skeleton |
| 3 | Clinical/FHIR extraction | parity-tested healthcare core |
| 4 | Medicines/CDS extraction | canonical catalogue and engine |
| 5 | Inventory/procurement extraction | reconciled pharmacy stock chain |
| 6 | Dispensing/sales extraction | state-machine transaction flow |
| 7 | Payments/finance/integrations | reconciled posting adapters |
| 8 | HQ/POS extraction | independently packaged clients |
| 9 | Data migration/certification | repeatable tenant cutover evidence |

No work package advances solely because code compiles. Each exit gate requires
behavioral parity, isolation, migration, reconciliation and rollback evidence.
