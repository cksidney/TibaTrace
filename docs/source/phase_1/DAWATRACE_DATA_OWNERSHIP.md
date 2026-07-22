# DawaTrace Data Ownership

## Ownership Policy

DawaTrace must operate from its own database. No target model may retain a
foreign key to a Mercato database, and no client may require a Mercato API to
complete a pharmacy transaction. Cross-product exchange uses versioned APIs or
events with stable external identifiers.

Ownership means DawaTrace defines lifecycle, validation, authorization,
retention, migration and audit rules for the record. A copied source identifier
does not transfer ownership back to Mercato.

## System-of-Record Map

| Data | Target owner | Scope | Source today | Transfer pattern | Notes |
| --- | --- | --- | --- | --- | --- |
| Tenant | DawaTrace tenancy | tenant | tenancy.Tenant | copy with `legacy_mercato_tenant_id` or OIDC federation decision | Never share a tenant table |
| Pharmacy organization/facility | organizations | tenant | Store and HealthcareFacility | copy and reconcile | Facility and store require an explicit relationship |
| Register/device | organizations | tenant/store | tenancy Register/Device | copy active pharmacy devices; reprovision secrets | New device keys and app identity required |
| User | identity | tenant/platform | users.User | copy or federate after approval | Password hashes only if approved and compatible |
| Role/capability | identity | tenant | users/RBAC | create DawaTrace role catalogue, map assignments | Exclude non-pharmacy roles |
| Approval evidence | identity/workflows | tenant | ApprovalSession/Event/Log | copy open/recent records as policy requires | Preserve factor, device and expiry evidence |
| Patient | patients | tenant | pharmacy.Patient and prescription.PatientReference | canonical merge with source crosswalk | Critical duplicate-model decision |
| Patient identifier | patients | tenant/system | PatientIdentifier plus pharmacy patient number | copy normalized identifiers | Uniqueness is tenant and assigning authority scoped |
| Consent | patients | tenant | PatientConsentReference | copy with provenance | Retention and lawful basis must be approved |
| Allergy | patients/clinical | tenant | PatientAllergy | copy and crosswalk FHIR IDs | Preserve status, severity and source |
| Medication profile | patients/clinical | tenant | PatientMedicationProfile | copy | Keep prescription/dispense provenance |
| Practitioner/prescriber | practitioners | tenant | pharmacy.Prescriber and prescription.Practitioner | canonical merge | Licence authority and expiry require normalization |
| Practitioner licence/role | practitioners | tenant | PractitionerLicence/Role, Prescriber fields | copy and normalize | No silent trust upgrade |
| Prescription | prescriptions | tenant | two current prescription aggregates | selected canonical model with immutable crosswalk | Critical blocker before extraction |
| Prescription line | prescriptions | tenant | Pharmacy PrescriptionLine and PrescriptionItem | line-level crosswalk | Preserve item/medicine identity and fill totals |
| Verification/review | prescriptions | tenant | DUR findings, review queue, PrescriptionVerification | migrate as immutable history | Status translations must be approved |
| Clinical override | cds/audit | tenant | PharmacistOverride, ClinicalAlertHistory | copy with actor/reason/device/time | Never collapse to a boolean |
| Dispense/fill | dispensing | tenant | DispenseRecord/Line and PrescriptionDispense/Fill | canonical merge with source IDs | Preserve sale, batch and prescription linkage |
| Label print | dispensing/audit | tenant | PharmacyLabelPrintEvent | copy | Reprint reason and actor are mandatory |
| Encounter | clinical | tenant | ClinicalEncounter | direct copy after ownership audit | Retain FHIR identity |
| Condition | clinical | tenant | ClinicalCondition | direct copy after ownership audit | Patient and encounter tenant must match |
| Observation | clinical | tenant | ClinicalObservation | direct copy after ownership audit | Preserve effective/issued chronology |
| Diagnostic report | clinical | tenant | ClinicalDiagnosticReport | direct copy after ownership audit | Preserve result references |
| Clinical document | clinical | tenant/object store | ClinicalDocument | metadata copy plus encrypted object transfer | Verify checksum and access policy |
| Medication administration | clinical | tenant | MedicationAdministrationRecord | direct copy after ownership audit | Preserve performer and encounter |
| National medicine | medicines | explicit global | NationalMedicine | copy/versioned content import | Global is explicit, never tenant-null by accident |
| Active ingredient/alias | medicines | explicit global or licensed edition | ActiveIngredient/IngredientAlias | copy only licensed content; version manifest | Approval required for content provider |
| Tenant medicine | catalogue | tenant | TenantMedicine | direct copy after medicine crosswalk | Commercial settings are tenant-owned |
| Store medicine | catalogue | tenant/store | StoreMedicine and StoreItem pharmacy subset | merge to canonical store activation | Preserve price, stock and location settings |
| Medicine barcode | medicines | global/source-specific | MedicineBarcode and Barcode | normalize with source/pack level | Collision rules required |
| Supplier | suppliers | tenant | catalog.Supplier | copy pharmacy-linked suppliers | Keep external accounting identifier |
| Supplier-medicine link | suppliers | tenant | Item supplier fields, SupplierItemProfile | canonical link import | Preserve latest cost and ordering status |
| Purchase order/line | procurement | tenant | purchasing PO/line/allocation | copy pharmacy-relevant documents | Preserve numbers, approvals and status |
| GRN/receipt line | procurement | tenant | GoodsReceipt/Line | copy with source identity | Required for batch and controlled receipt provenance |
| Inventory ledger | inventory | tenant/store | InventoryLedger | immutable copy then reconcile totals | Source event IDs retained for idempotency |
| Stock balance/snapshot | inventory | tenant/store/location | StockBalance/Snapshot/Bin balance | rebuild from ledger, compare to source | Projections are not authoritative |
| Batch | batches | tenant/store/medicine | inventory.Batch | copy with GRN source identity | Preserve expiry, quarantine, recall and quantities |
| Stock take/transfer | inventory | tenant/store | StockTake/Transfer families | copy open/recent history per policy | Resolve in-flight documents before cutover where possible |
| Return/quarantine/write-off | quality | tenant/store | PharmacyStockException | direct copy with stock-event crosswalk | Returned medicine remains unavailable until decision |
| Recall | recalls | tenant/global source | PharmacyRecall/Line | copy, preserve open block state | Closing does not imply release |
| Controlled register | controlled_drugs | tenant/store | ControlledDrugRegisterEntry | immutable copy and balance reconciliation | Statutory retention applies |
| Clinical knowledge version | cds | global or tenant edition | ClinicalKnowledgeVersion | licensed package import | Version and effective interval mandatory |
| CDS rule | cds | global plus tenant override | two current rule families | transform to canonical versioned schema | No demo rule promoted to production |
| CDS finding | cds | tenant | DURFinding/ClinicalAlert | copy as evaluation evidence | Store rule/version/evidence fingerprint |
| FHIR resource identity | fhir | tenant/resource | domain UUIDs and identifiers | preserve UUID where safe; maintain crosswalk otherwise | Never regenerate without redirect map |
| FHIR idempotency | fhir | tenant | FHIRIdempotencyRecord | copy unexpired/required records | Preserve request hash and response semantics |
| CodeSystem/ValueSet | terminology | explicit global or tenant | FHIR registrations | copy with canonical URL/version/provenance | Global and tenant uniqueness differ |
| Pharmacy transaction/line/tender/receipt | dispensing/payments | tenant/store | pharmacy-linked sales subset | copy full linked transaction | Dispensing owns transaction/lines and Payments owns tenders; both retain one transaction reference |
| Payment intent/attempt/provider transaction | payments | tenant | payments models | copy active and statutory history | Provider secrets are rotated, never copied raw |
| Refund/reversal | payments/sales | tenant | refunds and SaleReversal | copy as immutable corrections | No destructive edit of posted sale |
| Chart/account mapping/journal | finance | tenant | finance core | copy pharmacy mappings and linked journals | Reconcile opening balances and source links |
| Tax/eTims evidence | integrations/finance | tenant/store | taxation models/logs | copy if DawaTrace is tax system of record | Jurisdiction decision required |
| Audit record | audit | tenant | AuditLog and clinical audit | copy relevant retention window or full required history | Preserve original actor/source IDs |
| Domain event/outbox | workflows | tenant | events and prescription outboxes | drain or migrate pending records deliberately | Do not replay completed side effects |
| Report definition/export | reporting | tenant | reporting models | copy pharmacy definitions; regenerate exports if permitted | PHI export retention must be explicit |

## Shared Data Exchange Decisions

### Copy at cutover

Patients, practitioners, prescriptions, dispenses, batches, pharmacy inventory,
procurement, controlled records, pharmacy sales, finance source links, audit,
FHIR identity and idempotency must be copied into DawaTrace. They cannot remain
live foreign references.

### API reference

An external identity provider, payment provider, tax authority, insurer, EMR or
licensed content provider may remain external. DawaTrace stores its own adapter
configuration, external identifier, request/response evidence and reconciliation
state. External availability cannot bypass local clinical or tenant controls.

### Event synchronization

During a time-boxed coexistence window, Mercato may emit pharmacy source facts to
DawaTrace and receive settlement/reporting facts. Events must be versioned and
idempotent. Dual writes from one HTTP request to two databases are prohibited.

### No sharing

Database users, tables, Redis databases, Celery queues, media paths, encryption
keys, JWT signing keys, payment secrets, release signing keys and POS local data
directories are not shared.

## Identity Crosswalks

Each imported aggregate receives:

- DawaTrace UUID
- source system (`MERCATO_OS`)
- source tenant UUID
- source model and source UUID
- source natural/document number where present
- import batch and timestamp
- checksum or payload hash
- conflict/reconciliation status

Crosswalks are immutable. A unique constraint on source system, source tenant,
source model and source UUID prevents duplicate imports. Clinical and FHIR
references resolve through crosswalks during import, then store DawaTrace keys.

## Canonical Identity Blockers

### Patient

`pharmacy.Patient` stores operational demographics and optional sales Customer;
`prescription.PatientReference` stores clinical/FHIR identifiers. The target must
not choose by row count alone. Matching uses tenant, assigning authority,
identifier, verified contact and operator review. Ambiguous matches remain
separate and block dependent cutover.

### Practitioner

`pharmacy.Prescriber` and `prescription.Practitioner` overlap. Licence number must
be qualified by authority/country, and historical prescriptions retain the source
display even if a practitioner record is later merged.

### Prescription and dispense

The operational Pharmacy aggregate is currently connected to FEFO, sale and POS;
the prescription aggregate is connected to FHIR and clinical services. Phase 2
must define one canonical aggregate and adapters for both source families. No
automatic destructive merge is allowed.

## Global and Licensed Content

Global medicine, ingredient, terminology and clinical knowledge records require:

- explicit global scope flag
- publisher, source URL/identifier and licence
- content version and checksum
- effective and expiry dates
- activation/promotion approval
- supersession and rollback reference
- immutable published payload

Tenant overrides must reference the global rule/version and may narrow behavior;
they cannot silently weaken statutory or contraindicated controls.

## Migration Reconciliation

For every tenant and store, compare before acceptance:

- record counts and ID crosswalk coverage
- prescription line totals and remaining authorized quantities
- dispense quantities by prescription line and batch
- batch received, issued, quarantined, written-off and on-hand quantities
- inventory ledger sum versus rebuilt balance
- controlled-drug running balance versus physical/ledger evidence
- sale, tender, refund and reversal totals
- finance journal debit/credit balance and source-document coverage
- FHIR resource read-back and reference resolution
- open approvals, recalls, returns, payments and outbox records

Any mismatch produces an exception report and blocks tenant cutover.

## Privacy, Retention and Deletion

- Patient and clinical data follow an approved healthcare retention schedule.
- Controlled-drug, tax, finance and audit records follow statutory retention.
- Operational logs must not include PHI or secrets.
- Tenant deletion is a controlled legal workflow, not cascading ORM deletion.
- Backups, exports and local POS caches inherit the same retention and encryption
  requirements.
- Historical Mercato records become read-only after an accepted cutover and are
  removed only under a separately approved decommissioning plan.

## Ownership Decisions Requiring Approval

1. Canonical patient, practitioner, prescription and dispense models.
2. Identity strategy: copied local users, OIDC federation, or staged hybrid.
3. Global medicine and clinical-content provider/licensing model.
4. Tax/eTims system-of-record responsibility.
5. Coexistence duration and permitted event directions.
6. Statutory retention and data residency by deployment jurisdiction.
