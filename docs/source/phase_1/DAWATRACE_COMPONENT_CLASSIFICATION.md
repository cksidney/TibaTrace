# DawaTrace Component Classification

## Classification Rules

- `MOVE_TO_DAWATRACE`: preserve and copy the component into the standalone
  product, then remove its runtime dependency on Mercato.
- `SHARE_AS_LIBRARY`: extract or fork a pure, versioned package. DawaTrace pins a
  released artifact and never imports from a Mercato checkout at runtime.
- `REIMPLEMENT_AS_CONTRACT`: preserve observable behavior and data semantics but
  replace direct cross-domain imports with a DawaTrace-owned port, schema or event.
- `KEEP_IN_MERCATO`: leave the component and its ownership in Mercato.
- `REMOVE_FROM_DAWATRACE`: explicitly exclude it from the DawaTrace tree/build.
- `REQUIRES_DECISION`: ownership, canonical model, licence or product scope must be
  approved before movement.

Risk is extraction risk: L (low), M (medium), H (high), C (critical).

## Healthcare Domain Components

| ID | Source path / component | Owner | Imported dependencies | Database dependencies | API dependencies | Event dependencies | Frontend dependencies | Migration dependencies | Risk | Action and recommendation |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- | :---: | --- |
| 1 | `backend/apps/pharmacy/models.py` Patient/Allergy | patients | common | Tenant, Store, sales Customer | pharmacy patient/allergy API, FHIR Patient/AllergyIntolerance | audit on service writes | HQ/POS patient flow | pharmacy 0001-0007, tenancy, sales | H | `MOVE_TO_DAWATRACE`; retain IDs, remove Customer FK, add explicit identity link |
| 2 | `backend/apps/pharmacy/models.py` Prescriber | practitioners | common | Tenant, Store | pharmacy prescriber API, FHIR Practitioner bridge | audit | HQ/POS capture | pharmacy, tenancy | M | `MOVE_TO_DAWATRACE`; reconcile with Practitioner before cutover |
| 3 | `backend/apps/pharmacy/models.py` Prescription aggregate | prescriptions | common | patient, prescriber, Item, users, Store | `/api/v1/pharmacy/prescriptions/` | pharmacy audit/notifications | HQ and both POS clients | pharmacy, catalog, tenancy | C | `REQUIRES_DECISION`; choose canonical aggregate and publish ID/status map |
| 4 | `backend/apps/pharmacy/models.py` DUR rules/findings/overrides | cds | common | prescription, patient, Item, user | run-DUR, verify, override | audit and notification | HQ/POS DUR | pharmacy, catalog, users | H | `MOVE_TO_DAWATRACE`; retain as legacy rule adapter during engine convergence |
| 5 | `backend/apps/pharmacy/models.py` Dispense/Label | dispensing | common | prescription, Item, Batch, Sale, users | dispense, settle, label preview/mark | sale completed, audit, notification | HQ/POS payment and print | pharmacy, inventory, sales | C | `MOVE_TO_DAWATRACE`; preserve transaction semantics and decouple sale FK by local ID |
| 6 | `backend/apps/pharmacy/models.py` ControlledDrugRegisterEntry | controlled_drugs | common | Store, prescription, patient, prescriber, Item, Supplier, Batch, user | read-only controlled register | controlled facts stored as rows; audit | HQ/POS supervisor views | pharmacy, catalog, inventory, tenancy | H | `MOVE_TO_DAWATRACE`; make append-only and hash/source-reference controlled |
| 7 | `backend/apps/pharmacy/models.py` Recall/StockException | quality, recalls | common | Store, Item, Supplier, Batch, Sale, user | recall, return, write-off actions/reports | inventory and audit facts | HQ pharmacy stock | pharmacy, catalog, inventory, sales | H | `MOVE_TO_DAWATRACE`; preserve quarantine-by-default and explicit release |
| 8 | `backend/apps/pharmacy/models.py` ProductProfile | catalogue | common | Item | pharmacy products API | audit through service | HQ item/pharmacy pages, POS item flags | pharmacy, catalog | H | `MOVE_TO_DAWATRACE`; merge with pharmacy sale item after parity tests |
| 9 | `backend/apps/pharmacy/service.py` transaction orchestrator | dispensing | 16 Mercato apps | most pharmacy operational tables | all pharmacy actions/reports | sale, audit, notification, finance | HQ/POS | all pharmacy dependencies | C | `REIMPLEMENT_AS_CONTRACT`; first freeze tests, then split commands by context |
| 10 | `backend/apps/pharmacy/views.py`, serializers, URLs | pharmacy API | permissions, entitlements, domain service | all pharmacy models | `/api/v1/pharmacy/**` | none directly | HQ and both POS | none beyond models | H | `MOVE_TO_DAWATRACE`; version as DawaTrace API and keep compatibility adapter |
| 11 | `backend/apps/pharmacy_intake/**` | integrations | common permissions/viewsets | migration project, connector, run, staged row, mapping | `/api/v1/pharmacy-intake/**` | none | future intake HQ | pharmacy_intake 0001-0003, tenancy, users | M | `MOVE_TO_DAWATRACE`; retain staged/audited migration boundary |
| 12 | `backend/apps/prescription/models.py` prescription/order family | prescriptions | common | facility, practitioner, patient ref, NationalMedicine | dormant prescription API; FHIR MedicationRequest/Dispense | integration outbox/audit | no direct HQ route | prescription 0001-0008 | C | `REQUIRES_DECISION`; do not run two writable prescription aggregates in DawaTrace |
| 13 | `backend/apps/prescription/services/clinical_domain.py` | clinical | FHIR exceptions, pharmacy patient, prescription clinical models | tenant-owned clinical records | FHIR writes | FHIR audit via caller | none | prescription 0007-0008 | H | `MOVE_TO_DAWATRACE`; preserve invariant tests and keep as command boundary |
| 14 | `backend/apps/prescription/models.py` knowledge/rule models | cds | common timestamp model | ingredients, versions, rules, policies, alerts | CDS service only | clinical event/audit indirectly | no direct UI | prescription 0003-0005 | H | `MOVE_TO_DAWATRACE`; add provenance/licence/effective-state controls before content load |
| 15 | `backend/apps/prescription/services/cds`, `plugins/**` | cds | prescription models/plugins | knowledge tables | internal evaluation | clinical findings returned to pharmacy | HQ/POS through DUR | prescription | H | `MOVE_TO_DAWATRACE`; remove fail-open ambiguity and add missing rule executors |
| 16 | `backend/apps/prescription/providers`, queue/observability/security | integrations | prescription/FHIR | provider config, outbox, DLQ | provider adapters | durable outbound queue | none | prescription 0002 | H | `MOVE_TO_DAWATRACE`; rotate keys and formalize provider contracts |
| 17 | `backend/apps/prescription/models.py` clinical records | clinical | common tenant manager | encounter, condition, observation, report, document, administration | FHIR read/search/write | audit | none | prescription 0006-0008, tenancy | H | `MOVE_TO_DAWATRACE`; preserve explicit tenant ownership and identifiers |
| 18 | prescription terminology models | terminology | common tenant manager | terminology version, CodeSystem, ValueSet | FHIR terminology operations | audit | none | prescription 0006-0008 | H | `MOVE_TO_DAWATRACE`; retain explicit global-vs-tenant rules |
| 19 | `backend/apps/fhir/api`, converters, services, views | fhir | audit, catalog, common, events, pharmacy, prescription, tenancy, users | domain records and registry | `/api/fhir/r4/**` | FHIR write audit/outbox | external clients only | FHIR plus domain migrations | C | `MOVE_TO_DAWATRACE`; preserve R4 4.0.1 behavior and anti-corruption boundary |
| 20 | `backend/apps/fhir/models` idempotency | fhir | common | Tenant, request hash/status/resource | FHIR writes/Bundle | none | none | fhir 0001, tenancy | H | `MOVE_TO_DAWATRACE`; retain tenant-qualified uniqueness and replay semantics |

## Platform and Operational Components

| ID | Source path / component | Owner | Imported dependencies | Database dependencies | API dependencies | Event dependencies | Frontend dependencies | Migration dependencies | Risk | Action and recommendation |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- | :---: | --- |
| 21 | `backend/apps/common` model/context/permission subset | platform, tenancy | tenancy/users; currently also forecourt/sync | base model only | middleware/viewsets | request IDs | every client | none | H | `MOVE_TO_DAWATRACE`; copy reviewed primitives only and remove excluded imports |
| 22 | `backend/apps/tenancy` Tenant/Store/Register/Device subset | tenancy, organizations | broad Mercato imports | tenant/store/register/device | tenancy/provisioning API | device and lifecycle events | HQ/POS provisioning | 14 migrations plus many mode deps | C | `MOVE_TO_DAWATRACE`; create DawaTrace-only bootstrap and mode enum |
| 23 | `backend/apps/authn` | identity | users, tenancy, common | User, token blacklist | login/refresh/password | audit/communications | all clients | users/tenancy | H | `MOVE_TO_DAWATRACE`; rotate signing secrets and preserve token invalidation |
| 24 | `backend/apps/users`, `rbac` role/capability subset | identity | many Mercato apps | User, Role, Staff, assignment, overrides | user/role/RBAC API | approval/audit | HQ staff/roles, POS session | 15 user migrations | C | `MOVE_TO_DAWATRACE`; seed only DawaTrace capabilities and remove mode roles |
| 25 | users approval policy/session/event | identity, workflows | users, audit | approval tables | supervisor approval API | approval events | POS overrides | user migrations | H | `MOVE_TO_DAWATRACE`; preserve freshness, device and factor evidence |
| 26 | `backend/apps/entitlements` | platform licensing | audit/common/platform_admin/tenancy | plan, tenant entitlement, usage | entitlement API | usage events | HQ/POS module gates | 3 migrations | H | `REIMPLEMENT_AS_CONTRACT`; DawaTrace needs independent licensing, not platform_admin |
| 27 | `backend/apps/audit` | audit | common, entitlements | AuditLog | audit query API | accepts all domain audit facts | HQ audit/reporting | 3 migrations | M | `MOVE_TO_DAWATRACE`; remove entitlement back-reference and make retention explicit |
| 28 | `backend/apps/events` engine | workflows | catalog, finance, inventory, loyalty, purchasing, restaurant, sales | event/outbox/webhook/state | event API | all current domain events | none | 3 migrations | C | `REIMPLEMENT_AS_CONTRACT`; keep engine mechanics, replace processor allowlist/schemas |
| 29 | `backend/apps/communications` notification subset | notifications | audit, branding, platform_admin, users | template/log/attempt/in-app | communication API | subscription and domain notices | HQ notifications | 1 migration | H | `REIMPLEMENT_AS_CONTRACT`; preserve delivery mechanics, remove platform billing |
| 30 | `backend/apps/documents` sequences/identity | platform | audit, inventory, purchasing, restaurant, sales | sequence and document identity | document API | document registration | HQ/POS printing | 3 migrations | H | `MOVE_TO_DAWATRACE`; define pharmacy-only document types and number continuity |
| 31 | catalog NationalMedicine/MedicineBarcode/master governance | medicines | common, users | global medicine, import, review, version | catalog medicine APIs | governance audit | HQ catalogue | catalog 0001-0038 | C | `MOVE_TO_DAWATRACE`; retain IDs/provenance, isolate from mixed migration history |
| 32 | catalog TenantMedicine/StoreMedicine | catalogue | tenancy, suppliers, users | national medicine, tenant/store activation | catalogue/store APIs | catalogue writes | HQ/POS catalog sync | catalog, tenancy | H | `MOVE_TO_DAWATRACE`; make canonical commercial pharmacy item |
| 33 | catalog Item pharmacy fields and price resolution | catalogue | catalog, pricing, tax | Item, StoreItem, price/UOM/barcode | item search/sync | canonical dual writes | HQ/POS lookup | catalog mixed migrations | C | `REIMPLEMENT_AS_CONTRACT`; map to DawaTrace SaleItem, never copy mixed Item unchanged |
| 34 | catalog restaurant, bundles, retail promotions/wholesale | Mercato commerce | restaurant/promotions/sales | menu, bundle, promotion, wholesale rows | Mercato catalog APIs | retail/restaurant events | non-pharmacy HQ/POS | catalog mixed migrations | L | `REMOVE_FROM_DAWATRACE`; retain only migration mapping data needed for pharmacy items |
| 35 | catalog Supplier and medicine-supplier subset | suppliers | common/tenancy/users | Supplier, item links, contracts/prices as approved | supplier APIs | procurement events | HQ purchasing | catalog migrations | H | `MOVE_TO_DAWATRACE`; extract supplier master and tenant medicine links |
| 36 | inventory ledger/balance/location/bin | inventory | catalog, tenancy, documents, audit | Item, Store, locations, ledgers, projections | inventory API | stock facts | HQ/POS stock | 17 mixed migrations | C | `MOVE_TO_DAWATRACE`; preserve append-only ledger and rebuildable projections |
| 37 | `inventory/pharmacy_batches.py` and Batch | batches | audit, catalog, purchasing, users | Batch, GoodsReceiptLine, Item, Store | pharmacy/inventory batch API | FEFO audit | HQ/POS | inventory, purchasing, catalog | C | `MOVE_TO_DAWATRACE`; replace direct GRN FK with source document identity |
| 38 | stock take and transfer subset | inventory | users/documents/catalog | StockTake/Line, Transfer/Line/dispatch/receipt | inventory/transfer API | stock events | HQ/mobile | inventory migrations | H | `MOVE_TO_DAWATRACE`; retain multi-item controls and tenant/store validation |
| 39 | inventory production/recipe/kitchen/waste implementation | Mercato production | restaurant/factory/catalog | production recipe/run/batch/waste | inventory production API | production/waste events | Factory/Restaurant HQ | inventory mixed migrations | L | `REMOVE_FROM_DAWATRACE`; define pharmacy write-off separately |
| 40 | `backend/apps/purchasing` PO/GRN/discrepancy subset | procurement | catalog, inventory, tax, finance, users | PO, lines, allocation, GRN, supplier profile | purchasing API | receipt/supplier events | HQ purchasing | 21 mixed migrations | C | `MOVE_TO_DAWATRACE`; preserve receiving and controlled receipt idempotency |
| 41 | `backend/apps/replenishment` | procurement | catalog/inventory/purchasing | suggestions/requests/forecasts | replenishment API | replenishment events | HQ | own + purchasing deps | H | `REQUIRES_DECISION`; approve automatic replenishment scope before copy |
| 42 | sales pharmacy-used sale/register/tender/receipt subset | dispensing/payments | inventory, payments, tax, finance, users | business day, shift, session, Sale/Line/Tender/Receipt/Reversal | sales/shift API | sale/refund | HQ/POS | 27 mixed migrations | C | `REIMPLEMENT_AS_CONTRACT`; map transaction/lines to dispensing and tenders to payments through a legacy import adapter |
| 43 | sales restaurant/forecourt/loyalty/promotion behavior | Mercato commerce | excluded domains | shared sales rows | Mercato sales APIs | mode-specific events | non-pharmacy POS/HQ | sales mixed migrations | L | `REMOVE_FROM_DAWATRACE`; exclude handlers and fields not required by migrated facts |
| 44 | `backend/apps/payments` pharmacy tender/provider subset | payments | sales, tenancy, audit | config, credential version, intent, attempt, provider transaction, refund, reconciliation | payment/provider API | payment facts | HQ/POS tender | 14 mixed migrations | C | `MOVE_TO_DAWATRACE`; rotate credentials and preserve provider evidence/idempotency |
| 45 | taxation/eTims pharmacy receipt subset | integrations, finance | catalog, sales, finance, tenancy | tax profile/rate, invoice sequence, eTims mapping/log | taxation API | submission status | HQ/POS receipt | 7 migrations | H | `REIMPLEMENT_AS_CONTRACT`; approve jurisdiction scope and retain tax evidence |
| 46 | finance COA/mapping/journal/payables/cashbook/settlement | finance | sales, purchasing, inventory, tax, users | finance core tables | finance API | posting/reversal facts | HQ finance | 16 mixed migrations | C | `MOVE_TO_DAWATRACE`; preserve account mapping priority and idempotent journals |
| 47 | finance FactoryPaymentBatchSplit and factory imports | Mercato factory | factory/platform_admin | factory payment rows | factory finance API | factory events | Factory HQ | finance mixed migration | L | `REMOVE_FROM_DAWATRACE`; remove from target model graph |
| 48 | reporting framework and pharmacy report builders | reporting | broad Mercato apps | templates, widgets, schedules, artifacts | reporting/pharmacy report API | schedule jobs | HQ reports | 3 migrations | H | `REIMPLEMENT_AS_CONTRACT`; retain export engine with pharmacy projection allowlist |
| 49 | sync sale/inventory/payment/device core | workflows, pos | broad apps | SyncEvent and domain rows | `/api/v1/sync/**` | POS outbox contracts | both POS clients | 3 + domain migrations | C | `REIMPLEMENT_AS_CONTRACT`; define DawaTrace command/event schemas and versioning |
| 50 | sync Restaurant/Forecourt/loyalty/promotion handlers | Mercato modes | excluded apps | excluded domain rows | same sync endpoint | excluded events | non-pharmacy POS | mixed | L | `REMOVE_FROM_DAWATRACE`; no dormant handlers in target build |
| 51 | OMS, Restaurant, Forecourt, Factory, loyalty, HR, risk apps | Mercato domains | varied | unrelated domain tables | unrelated APIs | unrelated jobs/events | unrelated pages/screens | their migrations | L | `KEEP_IN_MERCATO`; DawaTrace may use only approved external contracts |

## Client and Shared Package Components

| ID | Source path / component | Owner | Imported dependencies | Database dependencies | API dependencies | Event dependencies | Frontend dependencies | Migration dependencies | Risk | Action and recommendation |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- | :---: | --- |
| 52 | `apps/hq/app/pharmacy/**`, pharmacy print | HQ pharmacy | HQ API/auth/module shell | none local | pharmacy/inventory APIs | none | Next.js | none | H | `MOVE_TO_DAWATRACE`; preserve workflows and replace Mercato navigation/brand |
| 53 | HQ catalog/inventory/purchasing/finance/payments/staff/roles/reports slices | HQ operations | broad HQ shell | none local | required operational APIs | none | shared components | none | C | `REIMPLEMENT_AS_CONTRACT`; extract route-by-route against DawaTrace APIs |
| 54 | HQ Restaurant/Forecourt/Factory/Retail/Wholesale/loyalty/OMS pages | Mercato UI | excluded APIs | none | excluded APIs | none | HQ shell | none | L | `REMOVE_FROM_DAWATRACE`; enforce route/build allowlist |
| 55 | HQ auth/API/error/flash/tenant shell | platform UI | shared/brand | browser session | auth/tenancy/API | observability | all HQ pages | none | H | `SHARE_AS_LIBRARY`; fork as versioned DawaTrace web shell package |
| 56 | Windows Pharmacy workspace/settlement/normalizers/labels | pos | React/shared/App callbacks | local cache through host | pharmacy API | local commands | Windows POS shell | none | C | `MOVE_TO_DAWATRACE`; preserve FEFO, DUR, batch and settlement tests |
| 57 | Windows cart, checkout, shift, sync, printing runtime | pos | shared, Electron, SQL.js | local SQLite/cache/outbox | sales/payment/sync/device APIs | outbox | pharmacy screens | none | C | `REIMPLEMENT_AS_CONTRACT`; extract from monolithic App into `pos-core` |
| 58 | Windows Restaurant/Forecourt/Wholesale/general Retail surfaces | Mercato POS | excluded modules | shared local DB | excluded APIs | excluded events | Windows App | none | L | `REMOVE_FROM_DAWATRACE`; do not retain hidden modes |
| 59 | Windows Electron packaging/update/identity | pos release | Electron builder, Mercato assets | local app paths | release/provisioning APIs | none | installer | none | H | `REIMPLEMENT_AS_CONTRACT`; new app ID, signing, icon, channel and data directory |
| 60 | Android Pharmacy workspace/normalizers/labels/receipts | mobile | React Native/shared/App callbacks | local SQLite/AsyncStorage | pharmacy API | local commands | Android shell | none | C | `MOVE_TO_DAWATRACE`; preserve batch and offline deduction tests |
| 61 | Android cart, checkout, shift, sync and local DB runtime | mobile | Expo/shared | local SQLite/outbox | sales/payment/sync/device APIs | outbox | pharmacy screens | none | C | `REIMPLEMENT_AS_CONTRACT`; extract pharmacy-safe `pos-core` with schema upgrades |
| 62 | Android Restaurant/Forecourt/Wholesale/general Retail/warehouse surfaces | Mercato mobile | excluded modules | shared local DB | excluded APIs | excluded events | Android App | none | L | `REMOVE_FROM_DAWATRACE`; exclude from source set and bundle |
| 63 | Android package/EAS/signing metadata | mobile release | Expo/Gradle | app data path | release/provisioning | none | Play distribution | none | H | `REIMPLEMENT_AS_CONTRACT`; assign DawaTrace package ID, keys and release tracks |
| 64 | `packages/shared/src/pharmacyBatchSafety.ts` and pharmacy capability types | pos shared | pure TypeScript | none | contract types only | none | both POS clients | none | M | `MOVE_TO_DAWATRACE`; publish in DawaTrace-owned package |
| 65 | pure shared pricing, tender, receipt, offline, diagnostics utilities | shared platform | brand/types | none | contract-neutral | none | HQ/POS | none | M | `SHARE_AS_LIBRARY`; fork, rename and pin only dependency-clean modules |
| 66 | `packages/shared/src/restaurantMenu.ts` and excluded mode helpers | Mercato UI | excluded types | none | excluded | excluded | excluded clients | none | L | `REMOVE_FROM_DAWATRACE`; keep out of package export graph |
| 67 | `packages/ui` | shared UI | React | none | none | none | HQ/POS | none | M | `SHARE_AS_LIBRARY`; fork only generic accessible primitives |
| 68 | `packages/brand` | product brand | zod/assets | none | release metadata | none | all clients | none | M | `REIMPLEMENT_AS_CONTRACT`; create DawaTrace brand manifest and assets |

## Tests, Documentation and Delivery

| ID | Source path / component | Owner | Imported dependencies | Database dependencies | API dependencies | Event dependencies | Frontend dependencies | Migration dependencies | Risk | Action and recommendation |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- | :---: | --- |
| 69 | pharmacy/catalogue backend tests | QA pharmacy | pharmacy plus operational fixtures | test DB | DRF client | event assertions | none | test settings no migrations | H | `MOVE_TO_DAWATRACE`; preserve first and make target-path imports |
| 70 | prescription/CDS/FHIR tests | QA clinical | exact FHIR runtime and domain models | test DB | FHIR views | Bundle/idempotency | none | migration tests separate | C | `MOVE_TO_DAWATRACE`; retain exact counts and vendor evidence provenance |
| 71 | inventory/procurement/sales/payment/finance dependency tests | QA operations | mixed apps | test DB | DRF client | ledger/posting events | none | mixed | H | `REIMPLEMENT_AS_CONTRACT`; select pharmacy-critical cases into target contract suites |
| 72 | Restaurant/Forecourt/Factory/Retail/loyalty test suites | Mercato QA | excluded apps | Mercato test DB | excluded APIs | excluded events | excluded clients | excluded | L | `KEEP_IN_MERCATO`; do not copy to DawaTrace |
| 73 | `docs/pharmacy/**` and pharmacy operational docs | product/docs | current code concepts | none | referenced routes | referenced events | operator guidance | none | M | `MOVE_TO_DAWATRACE`; validate content and rebrand only current truth |
| 74 | `docs/fhir/**`, ADRs and Phase 7 evidence | interoperability | FHIR runtime/tools | disposable test DB | FHIR API/vendor | Bundle | none | Phase 7 migration evidence | H | `MOVE_TO_DAWATRACE`; retain Mercato provenance and never relabel old evidence |
| 75 | `artifacts/fhir_phase_7_2_1`, `fhir_phase_7_2_2` | certification | external tools | disposable only | HAPI/Firely targets | none | none | none | H | `MOVE_TO_DAWATRACE`; archive immutable originals, regenerate for target release |
| 76 | FHIR certification scripts and `infra/fhir-certification` | certification | Docker, requests, FHIR runtime | disposable server | HAPI/Firely | Bundle | none | none | H | `MOVE_TO_DAWATRACE`; keep HAPI digest and make Firely environment explicit |
| 77 | POS package/publish scripts | release engineering | npm, Electron, Gradle/EAS | none | release endpoints | none | POS packages | none | H | `REIMPLEMENT_AS_CONTRACT`; create DawaTrace signing, checksums and provenance |
| 78 | root CI and compose templates | release engineering | all workspaces/apps | PostgreSQL/Redis | all APIs | workers | all clients | all migrations | C | `REIMPLEMENT_AS_CONTRACT`; new allowlisted CI, immutable images and independent infra |
| 79 | `deploy/**`, Mercato VPS scripts and domains | Mercato operations | Mercato compose/config | Mercato DB | Mercato routes | Mercato workers | Mercato HQ | Mercato migrations | C | `KEEP_IN_MERCATO`; never reuse credentials, paths or rollback targets |
| 80 | pharmacy screenshots/demo guide artifacts | product enablement | current UI | demo data | current routes | none | HQ/POS | none | M | `MOVE_TO_DAWATRACE`; preserve as historical input, recapture after extraction |

## Classification Totals

The matrix contains 80 classified component groups:

| Classification | Count |
| --- | ---: |
| `MOVE_TO_DAWATRACE` | 44 |
| `SHARE_AS_LIBRARY` | 3 |
| `REIMPLEMENT_AS_CONTRACT` | 18 |
| `KEEP_IN_MERCATO` | 3 |
| `REMOVE_FROM_DAWATRACE` | 9 |
| `REQUIRES_DECISION` | 3 |
| **Total** | **80** |

## Critical Classification Consequences

1. Rows 3 and 12 block data migration design until one canonical prescription
   aggregate and a reversible mapping are approved.
2. Rows 9, 22, 28, 33, 36-37, 40, 42, 46, 49, 57 and 61 define the principal
   transaction and data-integrity work. They require characterization tests before
   source movement.
3. `SHARE_AS_LIBRARY` means a versioned, dependency-clean fork or artifact. It does
   not permit a source-level runtime dependency on the Mercato repository.
4. Historical FHIR evidence moves only as provenance. DawaTrace certification must
   run again from a clean DawaTrace commit and immutable image.
