# DawaTrace Extraction Inventory

## Audit Scope and Method

This inventory was produced from the Mercato-OS worktree at commit
`5c84ad1781d843654b4bc446466384fee18394f1`. The worktree was already heavily
dirty and contains untracked Phase 7 source. Nothing was staged, deleted, moved,
deployed, or migrated during this audit.

The audit used source-path enumeration, Python AST import analysis, reverse-import
analysis, Django model and migration inspection, URL registration, task schedules,
client keyword tracing, package metadata, test discovery, and focused execution.
Generated directories such as `node_modules`, `.next`, `dist`, and `release` were
excluded from source counts.

Repository totals observed:

- 38 Django app directories
- 544 backend source files and approximately 166,845 source lines
- 261 backend migration files
- 82 backend test files
- 278 HQ source files, 39 Windows POS source files, 29 Android POS source files,
  and 27 shared package source files
- Healthcare roots alone (`pharmacy`, `prescription`, `fhir`, `pharmacy_intake`):
  138 source files, approximately 17,584 lines, and 19 migrations

## Core Healthcare Backend

| Source | Files / LOC | Migrations | Direct app dependencies | Reverse dependencies | Inventory decision |
| --- | ---: | ---: | --- | --- | --- |
| `backend/apps/pharmacy` | 11 / 7,954 | 7 | audit, catalog, common, communications, entitlements, events, finance, HR, inventory, payments, prescription, purchasing, sales, taxation, tenancy, users | catalog, FHIR, prescription, purchasing | Move behavior; split into pharmacy bounded contexts |
| `backend/apps/prescription` | 40 / 3,384 | 8 | catalog, common, FHIR, pharmacy | FHIR, pharmacy | Move clinical/FHIR behavior; reconcile duplicate prescription model |
| `backend/apps/fhir` | 80 / 5,255 | 1 | audit, catalog, common, events, pharmacy, prescription, tenancy, users | prescription | Move as interoperability boundary with runtime lock |
| `backend/apps/pharmacy_intake` | 7 / 991 | 3 | common | none | Move as data migration context |

### Pharmacy-specific models and services

`backend/apps/pharmacy/models.py` owns the current operational pharmacy flow:

- Patient, PatientAllergy and Prescriber
- Prescription, PrescriptionDiagnosis and PrescriptionLine
- PatientMedicationProfile
- tenant DUR rules, findings, review queue and pharmacist overrides
- refill authorization
- DispenseRecord, DispenseLine and PharmacyLabelPrintEvent
- ControlledDrugRegisterEntry
- PharmacyProductProfile
- PharmacyRecall, PharmacyRecallLine and PharmacyStockException

`backend/apps/pharmacy/service.py` implements product-profile synchronization,
controlled receipt logging, quarantine/release, recalls, return quarantine,
restock, write-off, reports, label generation, refill/status synchronization,
DUR, verification, FEFO dispensing, tender settlement, sales creation, finance
posting, audit, notifications and dashboard aggregation.

This service is the highest extraction-risk file because a single transaction
directly reaches at least 16 Django apps.

### Prescription and clinical models

`backend/apps/prescription/models.py` contains a second prescription family plus:

- healthcare facilities, practitioners and patient references
- prescriptions, items, dispenses, fills, histories, attachments and verification
- integration provider configuration, outbox and dead-letter records
- active ingredients, aliases, interaction and clinical knowledge models
- plugin marketplace records and clinical events
- tenant-owned Encounter, Condition, Observation, DiagnosticReport,
  ClinicalDocument and MedicationAdministrationRecord
- FHIR terminology versions, CodeSystem and ValueSet registrations

`ClinicalDomainService` is a real command boundary. It checks tenant context,
owned references, immutable patient links, required fields, status transitions,
chronology, values, transaction boundaries and idempotent update behavior before
persistence. It is not a generic ORM wrapper.

### FHIR modules

`backend/apps/fhir` contains:

- R4 API base, read/search/write views and Bundle processor
- resource-specific converters and lookup services
- tenant-qualified reference resolver
- resource registry and CapabilityStatement generation
- OperationOutcome and validation services
- CodeSystem/ValueSet `$validate-code` and `$expand`
- FHIRIdempotencyRecord
- conformance bundle and R4 runtime startup assertion

The registry exposes 19 measured resources: Organization, Location, Patient,
Practitioner, PractitionerRole, Medication, MedicationRequest,
MedicationDispense, MedicationStatement, AuditEvent, AllergyIntolerance,
Condition, Encounter, MedicationAdministration, Observation, DiagnosticReport,
DocumentReference, CodeSystem and ValueSet.

## Medicine Catalogue

The pharmacy medicine master is embedded in `backend/apps/catalog` alongside
general retail and restaurant data.

Healthcare components to extract:

- NationalMedicine, TenantMedicine, StoreMedicine and MedicineBarcode
- LegacyItemMasterMapping and pharmacy migration batches/decisions
- MasterListImport, MasterListImportRow and NewMedicineRequest
- clinical review, evidence, approval, version and data-quality records
- pharmacy identity, reconciliation, dual-write and governance services
- pharmacy catalogue import and cutover management commands
- pharmacy fields currently stored on Item: ingredient, class, dosage form,
  strength, prescription, controlled, FEFO, expiry, recall and dosage controls

Coupling to remove:

- Item also carries restaurant tiles, prep groups, modifier behavior, generic
  retail price, anti-theft and wholesale visibility.
- Catalog imports promotions, restaurant, OMS, replenishment, sales and finance.
- Catalog has 38 migrations with dependencies on restaurant, sales and taxation.

## Required Operational Dependencies

| Context | Required source slice | Database dependencies | Cross-domain contamination |
| --- | --- | --- | --- |
| Inventory/batches | `backend/apps/inventory/models.py`, `service.py`, `pharmacy_batches.py`, serializers/views | catalog Item, Store, Supplier, GoodsReceiptLine, users/documents | production recipes, kitchen/bar locations, restaurant and OMS imports |
| Procurement/suppliers | `backend/apps/purchasing`; supplier subset of `catalog` | Store, Item, Supplier, inventory location/batch, tax, finance | replenishment and branding/email are directly imported |
| Sales/register | pharmacy-used subset of `backend/apps/sales` | customer, business day, shift, session, Sale, SaleLine, allocation, Tender, Receipt, reversal | same app imports restaurant, forecourt, loyalty and promotions |
| Payments | `backend/apps/payments` provider config, intent, attempt, transaction, refund, reconciliation | tenant, store/register, sale | OMS imports and Mercato credential/bootstrap naming |
| Tax | pharmacy-used subset of `backend/apps/taxation` | item, sale, tenant/store | Mercato eTims and general commerce assumptions |
| Finance | account map, COA, journal, payable, cashbook, settlement and reconciliation subsets | sales, purchasing, inventory, tax | factory-specific payment split and platform-admin imports |
| Reporting | pharmacy reports plus generic export/schedule framework | broad read dependencies | currently imports forecourt, HR, OMS and platform admin |
| Sync | device/outbox sale, stock and approval contracts | sales, inventory, payments, users, tenant/device | one service also executes restaurant, forecourt, loyalty and promotion flows |
| Documents | sequences and document identity | stock take, PO/GRN, sale/receipt | restaurant document paths are mixed in |
| Notifications | in-app and communication delivery | tenant, user, audit | platform subscription behavior is mixed in |

Important schema couplings include `inventory.Batch.goods_receipt_line` directly
referencing purchasing, pharmacy dispense records directly referencing sales,
pharmacy patients optionally referencing sales Customer, and controlled register
entries referencing catalog Supplier, inventory Batch and users.

## Identity, Tenant, RBAC and Audit

Required components:

- `backend/apps/common`: TimestampedModel, TenantScopedModel,
  StrictTenantManager, tenant context, request middleware, permissions and viewsets
- `backend/apps/tenancy`: Tenant, Store, Register, Device and heartbeat/incident
  behavior, but not unrelated mode bootstrap
- `backend/apps/authn`: JWT authentication, login, refresh and password control
- `backend/apps/users` and `backend/apps/rbac`: User, Role, StaffProfile,
  StaffAssignment, capability evaluation, approval policies/sessions/events
- `backend/apps/audit`: tenant-scoped audit records and service
- pharmacy capability constants and seed behavior currently spread across common,
  users, tenancy, entitlements and pharmacy-intake migrations

Current risk: `common` imports forecourt and sync, `tenancy` imports almost every
business mode, and `users` imports restaurant/HR/sales. These app folders cannot
be copied wholesale without retaining unrelated product modes.

## Workflows, Events and Background Tasks

Required workflow components:

- `events.DomainEvent`, `OutboxEvent`, EventStore and processor state
- event emission, signing, webhook delivery and replay
- pharmacy sale payload source marker
- payment webhook, stale-intent and reconciliation tasks
- supplier performance/contract tasks used by procurement
- replenishment task if automatic pharmacy replenishment is retained
- reporting scheduler/export task
- communication delivery task
- prescription IntegrationOutbox, DeadLetterQueue and queue processor

There is no dedicated pharmacy Celery task module. Current global beat imports
payment, reporting, risk, platform billing, replenishment, supplier, loyalty and
communication schedules. DawaTrace needs an explicit allowlist and must not start
unrelated Mercato jobs.

The current event engine has no first-class prescription/dispense/controlled
event vocabulary. Pharmacy settlement emits generic `sale_completed` with
`source="pharmacy"`; controlled-drug events are database records. Phase 2 must
define DawaTrace contracts before decoupling direct writes.

## HQ Pharmacy Surface

Primary pharmacy UI:

- `apps/hq/app/pharmacy/page.tsx`
- `apps/hq/app/pharmacy/pharmacyWorkspace.ts`
- `apps/hq/app/pharmacy/pharmacy.module.css`
- `apps/hq/app/inventory/pharmacy-expiry/page.tsx`
- `apps/hq/lib/pharmacyPrint.ts`

Required shared shell:

- authentication/session guard, API client/base URL, entitlement/module access
- tenant/store context, navigation, error/flash surfaces and print utilities
- item setup slices for medicine/catalogue controls
- inventory, purchasing, finance, payment, staff/roles and report slices

The HQ is one Next.js application with 278 source files. Nineteen files contain
direct healthcare terms, but the operational pharmacy journey also depends on
generic catalog, purchasing, inventory, finance, staff, roles, reports, devices,
downloads and shift-control routes. Extraction must build a DawaTrace route
allowlist and a new navigation model rather than copy all pages.

## Windows Pharmacy POS

Direct healthcare files include:

- `apps/pos-windows/src/screens/PharmacyPosWorkspace.tsx`
- `apps/pos-windows/src/screens/PharmacySettlementPanel.tsx`
- `apps/pos-windows/src/pharmacyPos.ts`
- `apps/pos-windows/src/pharmacyLabelPrint.ts`
- pharmacy paths inside `src/App.tsx`, `SalesRmsStyleScreen.tsx`, styles,
  Electron main/preload and global types

The Windows POS is not currently separable by copying its pharmacy screen.
`src/App.tsx` is over 16,000 lines and owns login, provisioning, catalog, cart,
pricing, tenders, shift control, sync, printing and all business modes. It blocks
queued offline completion in Pharmacy mode, while shared batch safety can evaluate
offline FEFO. DawaTrace must resolve that policy deliberately.

Packaging is Mercato-branded (`com.mercatoos.poswindows`, Mercato product name,
icons, installer script and release channel) and requires independent identity,
signing and update metadata.

## Android Pharmacy POS

Direct healthcare files include:

- `apps/pos-android/src/screens/PharmacyPosWorkspace.tsx`
- `apps/pos-android/src/pharmacyPos.ts`
- `apps/pos-android/src/pharmacyLabelPrint.ts`
- `apps/pos-android/src/pharmacyReceiptPrint.ts`
- `apps/pos-android/src/offline/pharmacyBatchResolver.ts`
- pharmacy persistence and flow inside `src/offline/db.ts`, `App.tsx` and the
  shared sales screen

`App.tsx` combines Retail, Restaurant, Wholesale, Forecourt and Pharmacy. Android
can queue qualifying generic sales offline and contains repeated-sale deduction
tests, but prescription workflow actions still rely on pharmacy APIs. The target
offline policy must distinguish OTC sale, reviewed prescription dispense, external
authorization, controlled medicine and provider-backed payment.

Android package/version/build configuration is Mercato-owned and needs new app ID,
signing keys, release tracks and update policy.

## Shared Frontend Packages

Healthcare-relevant shared files are:

- `packages/shared/src/pharmacyBatchSafety.ts`
- pharmacy capabilities in `packages/shared/src/posSessionCapabilities.ts`
- pharmacy API methods and schemas in `packages/shared/src/api.ts`
- exports in `packages/shared/src/index.ts`

The pharmacy clients also need pure utilities for pricing, cart saleability,
fractional quantity, offline policy, tender ordering, receipt rendering,
observability and diagnostics. Restaurant menu and Mercato brand/package naming
must not enter DawaTrace.

## Migration Inventory

| App | Count | External migration dependencies |
| --- | ---: | --- |
| pharmacy | 7 | catalog, inventory, sales, tenancy; user through `AUTH_USER_MODEL` |
| prescription | 8 | catalog, tenancy; self |
| FHIR | 1 | tenancy |
| pharmacy_intake | 3 | tenancy, users |
| catalog | 38 | inventory, restaurant, sales, taxation, tenancy |
| inventory | 17 | catalog, OMS, purchasing, tenancy |
| purchasing | 21 | catalog, inventory, replenishment, taxation, tenancy |
| sales | 27 | catalog, forecourt, inventory, OMS, tenancy |
| payments | 14 | OMS, sales, tenancy |
| finance | 16 | catalog, inventory, purchasing, sales, tenancy |

The extraction cannot replay these histories unchanged into an isolated product.
Phase 2 must create a DawaTrace baseline migration from reviewed target models,
plus explicit import migrations that retain legacy IDs and source provenance.

## Test Inventory

Healthcare-focused backend tests include:

- six operational pharmacy files, pharmacy catalogue and national medicine tests
- four in-app prescription/CDS/interoperability test files
- five Phase 7 FHIR/certification/clinical round-trip files
- inventory, purchasing, tender, payment, finance, tax, shift and reversal tests
- RBAC, password, tenant isolation, SaaS and security tests

Client tests include Pharmacy workspace/normalization, FEFO/batch safety, Windows
and Android sale guards, Android offline deduction certification, label/receipt
printing, session capabilities and offline tender policy.

The exact Phase 1 run is 608 backend tests and 51 Node tests, all passing. This is
not a clean DawaTrace repository test run and does not certify an extracted build.

## Documentation and Evidence

Move or adapt:

- `docs/pharmacy/**`, pharmacy operator/go-live/support documents and release notes
- `docs/fhir/**`, FHIR ADRs, vendor/onboarding guides and Phase 7 evidence
- `artifacts/fhir_phase_7_2_1/**`, `artifacts/fhir_phase_7_2_2/**`
- pharmacy POS/HQ screenshots and the demo pharmacy guide
- FEFO, controlled register, intake, labels, reports and offline policy documents

Exclude Mercato marketing and unrelated product-mode documentation. Historical
evidence must retain its original Mercato source/commit label; it must not be
rebranded as evidence from a DawaTrace release.

## Seed, Demo and Migration Commands

Move after dependency isolation:

- `pharmacy_seed_demo`
- `import_pharmacy_catalogue`
- clinical tenant ownership and UUID lookup audit/repair commands
- pharmacy master assessment/generation/reconciliation/cutover commands
- stock snapshot rebuild
- tenant/store/device bootstrap rewritten for DawaTrace-only modes

Demo commands must remain environment-gated, idempotent and forbidden against
non-demo tenants. No unlicensed clinical rule content may be included.

## Configuration Inventory

Backend configuration to rename and independently provision includes:

- Django secret, debug, hosts, CORS, CSRF and proxy settings
- PostgreSQL, Redis, cache, Celery broker/result and event engine settings
- email and HQ URL
- tenant routing/root-domain settings
- FHIR public URL, write switch, Bundle/search/terminology limits, terminology
  cache/timeout and allowed absolute reference hosts
- payment credential encryption and provider settings
- M-Pesa base URL, consumer credentials, shortcode, passkey and callback URL
- taxation/eTims credentials and device/branch mappings
- media/static/object-store and observability settings
- POS API URL, printer, timeout, fullscreen, sync and release URL settings
- Android Node/build/signing and Expo/EAS configuration
- HQ public API, base path, observability and release URLs

No Mercato default URL, email sender, domain, Redis key prefix, database name,
package ID, signing key or release path may survive as a DawaTrace production
default.

## Direct Coupling Summary

1. Django settings load every product mode and import forecourt startup validation.
2. Operational pharmacy service directly imports 16 other apps.
3. Catalog, inventory, sales, finance, sync, reporting, users and tenancy mix
   DawaTrace-required behavior with excluded modes.
4. Pharmacy and prescription contain overlapping patient, practitioner,
   prescription and dispense concepts.
5. FHIR converters bridge both model families and shared Mercato identity/catalog.
6. Both POS clients use monolithic app roots for all business modes.
7. Migration histories contain Restaurant, Forecourt, OMS and Factory coupling.
8. Deployment, branding, package IDs and release channels are Mercato-specific.

These findings make a controlled extraction feasible, but rule out a folder-copy
or delete-in-place approach.
