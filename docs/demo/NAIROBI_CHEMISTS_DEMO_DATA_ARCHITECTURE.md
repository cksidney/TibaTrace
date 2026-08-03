# Nairobi Chemists — Demo Data Architecture

**Status:** Phase 1 audit complete. **Stage 1 foundation implemented** — tenant
designation, scenario ownership, safety gates, classification and the dry-run
manifest. No transactional demo data is generated yet.

**Audited at:** `68b0e9c` on `main`, working tree clean.

---

## 1. Blockers found during the audit

The specification opens with a premise the repository does not support. Both items
below need a decision before any seed logic is written.

### 1.1 RESOLVED — Nairobi Chemists (`nrbchem`) is the authorised demo tenant

The blocker below stands as the record of what was found. It has since been
resolved by decision: `nrbchem` is designated the demonstration tenant, the slug
`nairobi-chemists` is not used, and no second tenant is created. Designation is
an explicit, audited act — it is **not** applied by migration, and the tenant is
not designated yet.

### 1.1 (original finding) Nairobi Chemists is production's only *live* tenant

The brief describes "the existing demo tenant: Nairobi Chemists" and targets
`--tenant-slug=nairobi-chemists`. What actually exists:

| Where | Finding |
|---|---|
| Repository source | No reference to "Nairobi Chemists" or `nairobi-chemists` anywhere |
| Local dev database | Tenants are `default`, `tenant-a`, `tibatrace-demo` — no Nairobi Chemists |
| **Production** | **`nrbchem` / "Nairobi Chemists" / `ACTIVE` — and it is the *only* tenant** |

Two mismatches follow:

- **The slug is `nrbchem`, not `nairobi-chemists`.** The command in the brief would
  fail to resolve a tenant, or — worse, if a fallback created one — would silently
  create a *second* Nairobi Chemists alongside the real one.
- **It is not marked as a demo tenant, because no such marker exists** (see §1.2).
  It is the live production tenant of the only customer on the platform.

Production record counts for `nrbchem`, read-only:

```
users                       1
locations                   0
patients                    0
commercial SKUs             0
inventory ledger entries    0
inventory batches           0
prescriptions               0
dispensing episodes         0
purchase orders             0
audit events                0
```

So the tenant is currently an **empty shell** — configured but not yet trading. That
is the one piece of good news: seeding it would not overwrite existing business
records today. But it is still the production tenant of a real customer, and the
brief's own Phase 27 gate says the command must refuse to run when the tenant is not
explicitly marked as demo. Under the brief's own rules, `nrbchem` must be refused.

**This needs an explicit decision.** The plausible readings are:

| Reading | Consequence |
|---|---|
| Seed `tibatrace-demo` instead, and leave production alone | Safe. Recommended default |
| Create a *new* demo tenant, e.g. `nairobi-chemists-demo` | Safe. Clean separation |
| Genuinely seed production `nrbchem` with 4 years of synthetic trading history | **Contaminates a real customer's tenant with fabricated data.** Needs deliberate, explicit sign-off, and probably should not happen at all |

I have not written a line of seed logic pending that answer.

### 1.2 RESOLVED — `Tenant.is_demo` added

`Tenant.is_demo` is now a real boolean field (`tenancy.0003_tenant_is_demo`),
defaulting `False` and never set by migration.

### 1.2 (original finding) There is no demo marker on `Tenant`

Phase 27 requires refusal when "tenant is not explicitly marked as demo". The model
has no such field:

```
Tenant fields: id, created_at, updated_at, name, slug, status,
               country_code, time_zone, metadata
```

Two options:

- **`metadata` JSON key** (`{"is_demo": true}`) — no migration, weaker guarantee, not
  indexable, easy to set by accident.
- **A real `is_demo` boolean field** — needs a migration, and is the honest choice for
  a flag whose entire job is to gate a destructive operation. Recommended.

Either way this must exist **before** the seed command, because the command's primary
safety gate depends on it.

---

## 2. What the platform actually offers

### 2.1 Authoritative service modules

Writes must go through these. Direct model creation bypasses state machines, ledger
posting, tenant scoping and audit.

| Domain | Module |
|---|---|
| Tenancy | `apps/tenancy/services.py` |
| Identity / RBAC | `apps/identity/services.py` |
| Pharmacy network / premises | `apps/pharmacy_network/services.py` |
| Practitioners | `apps/practitioners/services.py` |
| Patients | `apps/patients/services.py` |
| Medicines | `apps/medicines/services.py` |
| Customers | `apps/customers/services.py` |
| Inventory | `apps/inventory/services.py` |
| Recalls | `apps/inventory/recalls/services.py` |
| Procurement | `apps/procurement/services/` |
| Prescriptions / dispensing | `apps/prescription/services/` (11 modules) |
| Clinical decision support | `apps/cds/services.py` |
| Clinical | `apps/clinical/services.py` |
| POS transactions | `apps/pos_transactions/services.py` |
| Sales | `apps/sales/services.py` |
| Insurance / claims | `apps/insurance/services/` (7 modules) |
| Reporting | `apps/platform/reporting/services.py` |
| FHIR | `apps/fhir/services/` |
| Terminology | `apps/terminology/services.py` |
| Crosswalks | `apps/crosswalks/services.py` |

### 2.2 The inventory ledger is the model for how seeding must work

`apps/inventory/services.py` exposes exactly the shape the brief demands:

```
InventoryLedgerService.post_entry(...)          # append-only, the only write path
InventoryBalanceService.apply_ledger_entry(...) # projection, derived
InventoryBalanceService.rebuild_all_balances(tenant)
InventoryReceiptService.post_receipt(...)
FEFOAllocationService.allocate_stock(...)
InventoryReservationService.reserve_stock / release_reservation / fulfill_reservation
StockTransferService.request_transfer / approve_transfer / ...
```

`InventoryBalance` documents itself as a *"Balance projection updated by the ledger
service."* — so Phase 10's "do not write InventoryBalance directly" is already the
architecture, and `rebuild_all_balances` gives the validation engine a free integrity
check: rebuild and compare.

### 2.3 Immutable models — reset cannot delete these

| Model | Rule |
|---|---|
| `AuditEvent` | "Audit events are immutable" |
| `ClinicalOverride` | "Clinical overrides are immutable" |
| `PharmacistVerification` | "Pharmacist verification records are immutable" |
| `LegacyIdentifierCrosswalk` | "Legacy crosswalks are immutable after creation" |
| Supplied `Prescription` instructions | immutable; corrections require a new prescription |
| `IntegrationEvidence` | immutable audit evidence |
| POS printing documents | immutable documents + durable print jobs |
| Procurement PO revisions | immutable revisions |

**Consequence for Phase 2:** `--reset-demo-data` cannot physically delete demo records
in these tables. The only honest reset strategies are:

1. **Disposable tenant recreation** — seed into a throwaway tenant, drop the whole
   tenant to reset. Clean, and the only one that fully satisfies "immutable records
   must not be deleted". **Recommended.**
2. Archival / soft-marking, leaving immutable rows in place.

A reset that quietly deletes audit rows would violate the repository's own stated
policy, and I will not implement one.

### 2.4 State machines

Transitions are enforced, not free-form:

- `apps/prescription/pos_dispensing_services.py::transition_state`
- `apps/prescription/services/workflow.py::transition`
- `apps/pharmacy_network/services.py::transition`
- `apps/integrations/views.py::VALID_TRANSITIONS` (activation lifecycle)

Any generator that wants an episode in `SUPPLIED` must walk it there through the real
transitions, which also produces the audit trail a demo needs.

### 2.5 Existing seed commands — precedent and reusable parts

| Command | Lines | Use |
|---|---|---|
| `platform/seed_hq_workspaces` | 1,192 | Broadest existing seeder; the closest precedent |
| `platform/seed_demo_tenant` | 284 | Tenant → org → branches → catalogue → pricing → shift |
| `prescription/seed_pos_dispensing_demo` | — | POS dispensing scenarios |
| `prescription/seed_clinical_dispensing` | — | Clinical paths |
| `procurement/seed_procurement` | — | Procurement history |
| `inventory/seed_inventory`, `seed_purchasing_inventory_demo` | — | Stock |
| `sales/seed_sales`, `insurance/seed_insurance_demo`, `cds/seed_pos_clinical_demo` | — | Domain slices |
| `medicines/seed_medicine_catalogue` | — | Catalogue |

The demo engine should **orchestrate these**, not duplicate them.

Integrity checkers already exist and should back the Phase 25 validation engine
rather than being reimplemented:

```
inventory/check_inventory_integrity        inventory/check_transfer_integrity
inventory/rebuild_inventory_balances       procurement/check_procurement_integrity
sales/check_sales_integrity                insurance/check_insurance_claim_integrity
cds/check_pos_clinical_integrity           prescription/check_pos_dispensing_integrity
prescription/check_clinical_dispensing_integrity
prescription/audit_tenant_managers         prescription/audit_clinical_lookup_safety
prescription/audit_clinical_tenant_ownership
```

### 2.6 The demo-seed safety guard already exists

`apps/core/demo_seed.py` (7 functions) already implements most of Phase 27:

- `PRODUCTION_ENVIRONMENTS = {production, prod, live}` — refuses outright, and
  `--allow-demo-seed` **cannot** override it
- `--allow-demo-seed` required outside `DEBUG`
- Credentials from `DAWATRACE_DEMO_SEED_PASSWORD`, validated, never echoed

The new command must reuse this rather than inventing a second mechanism. What it does
*not* yet cover: the per-tenant demo marker (§1.2), notification-sending checks, and
live-provider-credential checks.

### 2.7 Notifications can be seeded safely

`NotificationOutbox` exists, so Phase 19's "do not send real email/SMS" is satisfiable
by writing to the outbox without a dispatcher run.

---

## 3. Domain coverage: what the brief asks for vs what exists

| Brief phase | Domain exists? | Note |
|---|---|---|
| 3 Branches / locations | ✅ `organizations` | |
| 4 Users / RBAC | ✅ `identity` | 29 capabilities available |
| 5 Premises / regulatory | ✅ `pharmacy_network` | truth labels supported |
| 6 Practitioners / patients | ✅ `practitioners`, `patients` | |
| 7 Catalogue | ✅ `medicines` | reuse, do not duplicate |
| 8 Pricing | ✅ `pricing` | versioned price books |
| 9 Suppliers / procurement | ✅ `procurement` | |
| 10 Inventory | ✅ `inventory` | append-only ledger |
| 11 Transfers | ✅ `inventory` | `StockTransferService` |
| 12 Prescriptions / CDS | ✅ `prescription`, `cds` | |
| 13 Reservations / FEFO | ✅ `inventory` | `FEFOAllocationService` |
| 14 POS / shifts | ✅ `pos_shift`, `pos_transactions` | |
| 15 Insurance / claims | ✅ `insurance` | 7 service modules |
| **16 Finance** | ❌ **no finance app** | **See below** |
| 17 Recalls | ✅ `inventory/recalls` | |
| 18 National integrations | ✅ `integrations` | truth labels supported |
| 19 Notifications | ✅ `notifications` | outbox available |
| 20 Reporting | ✅ `platform/reporting` | 99-pack catalogue |

**Phase 16 (Finance) has no domain to post through.** There is no finance,
accounting or general-ledger app. The brief asks for trial balance, P&L, balance
sheet, VAT, AR/AP ageing and close packs — none of which have models or services.
Implementing them would mean **building a finance module**, which is a separate
project, not demo seeding. Phase 16 must be dropped or explicitly rescoped.

---

## 4. Honest scope assessment

The brief is 28 phases across ~19 domains, targeting 100,000+ ledger entries,
75,000–150,000 sales events, 20,000–30,000 patients and four years of history — all
routed through domain services rather than bulk insert — plus a validation engine, a
manifest format, a storyboard, an operations guide, a test suite, and a full
repository regression run across backend, HQ web, Windows POS and Android.

That is a multi-week engineering programme for a team, not a single change. Anyone
claiming otherwise is going to deliver row counts instead of working demos, which the
brief itself warns against:

> *"Do not claim success merely because rows were inserted."*

Two hard constraints make the headline numbers additionally unsafe:

- **Service-routed generation is slow by construction.** Every dispensing episode
  walks a state machine, runs real CDS screening, allocates FEFO stock and posts
  ledger entries. At 75,000–150,000 events that is hours of runtime per seed, and it
  cannot be bulk-inserted without bypassing exactly the logic that makes the demo
  meaningful.
- **The production host has ~4 GB free on a 38 GB disk shared with five other
  applications.** 100,000+ ledger rows plus indexes is survivable; the point is that
  headroom must be checked before, not after.

### Recommended staging

| Stage | Deliverable | Realistic |
|---|---|---|
| **0** | This audit + the two blocker decisions | done / pending you |
| **1** | Demo marker, ownership models, safety gates, manifest, `--dry-run`, `--validate-only` | one focused change |
| **2** | Orchestration of the existing seeders + `small` profile end-to-end, with tests | one focused change |
| **3** | `regional-chain` at reduced scale (hundreds, not hundreds of thousands) | one focused change |
| **4** | Edge-case catalogue + storyboard against deterministic references | one focused change |
| **5** | Validation engine wrapping the existing integrity checkers | one focused change |
| **6** | Scale-up, only after measuring stage 3 runtime | separate |

---

## 5. Decisions needed before implementation

1. **Which tenant?** `tibatrace-demo`, a new `nairobi-chemists-demo`, or — with
   explicit sign-off — production `nrbchem`. The slug in the brief
   (`nairobi-chemists`) matches nothing that exists.
2. **Demo marker:** real `is_demo` field (migration, recommended) or `metadata` key.
3. **Reset strategy:** disposable-tenant recreation (recommended, and the only one
   compatible with immutable audit records) or archival.
4. **Phase 16 Finance:** drop, or rescope to what `sales` / `pos_transactions`
   already record.
5. **Scale:** confirm reduced first-pass targets rather than the headline numbers.

Nothing is implemented pending 1–3.


---

## 6. Finance scope (authoritative)

Audited against the repository, not assumed.

### Exists — may be seeded through its own services

| Capability | Models |
|---|---|
| Payment intents / tenders | `prescription.PaymentIntent`, `PaymentTender` |
| Payment attempts and settlement | `PaymentAttempt`, `PaymentSettlement` |
| Provider events, reversals | `PaymentProviderEvent`, `PaymentReversal` |
| POS transactions | `pos_transactions.PosTransaction`, `PosTransactionLine` |
| Business days, registers, sessions | `pos_shift.BusinessDay`, `PosRegister`, `RegisterSession` |
| Insurer remittance and payment | `insurance.InsuranceRemittance`, `InsuranceRemittanceLine`, `InsurancePayment`, `InsurancePaymentAllocation` |
| Pricing and agreements | `sales.PriceList`, `PriceListEntry`, `CustomerPriceAgreement` |

### Does not exist — excluded, and recorded in every manifest

| Excluded | Reason |
|---|---|
| General ledger | no GL app, model or service |
| Trial balance | derived from a GL that does not exist |
| Profit and loss | derived from a GL that does not exist |
| Balance sheet | derived from a GL that does not exist |
| VAT return | no VAT domain |
| AR ageing | no accounts-receivable domain |
| AP ageing | no accounts-payable domain |
| Supplier invoices | no `SupplierInvoice` model |
| Close packs | no period-close domain |

A grep for `SupplierInvoice`, `AccountsReceivable`, `GeneralLedger`,
`TrialBalance` and `JournalEntry` across every `models.py` returns nothing.
The exclusions are carried in `profiles.py` and printed on every dry run, so a
demo cannot silently imply a finance capability the platform does not have.

---

## 7. What Stage 1 delivers

| Component | Location |
|---|---|
| `Tenant.is_demo` | `apps/tenancy/models.py`, migration `tenancy.0003` |
| Designation workflow | `apps/platform/management/commands/designate_demo_tenant.py` |
| Scenario ownership | `apps/platform/demo/models.py`, migration `platform.0003` |
| Safety gates | `apps/platform/demo/safety.py` |
| Classification | `apps/platform/demo/classification.py` |
| Manifest | `apps/platform/demo/manifest.py` |
| Pilot profile | `apps/platform/demo/profiles.py` |
| Inspection command | `apps/platform/management/commands/inspect_demo_tenant.py` |
| Engine entrypoint | `apps/platform/management/commands/seed_demo_scenario.py` |
| Tests | `backend/tests/test_demo_foundation.py` (37) |

### Scenario states

`PLANNED → DRY_RUN_COMPLETE → APPROVED → RUNNING → COMPLETED → ARCHIVED`, with
`FAILED` reachable from the working states. Transitions are enforced by
`DemoScenarioRun.transition_to`; `ARCHIVED` is terminal. A run cannot jump from
`PLANNED` to `COMPLETED` without a dry run and an approval in between.

### Archival, not deletion

`DemoScenarioObject.reset_eligible` is `False` for the eight immutable domains.
Reset supersedes a run and marks its objects archived; nothing deletes audit
events, ledger entries, clinical overrides, pharmacist verifications, supplied
prescriptions, integration evidence, POS documents or PO revisions.
`--reset-demo-data` currently refuses outright rather than half-implementing it.

### One gate worth knowing about

`FHIR_WRITE_INTERACTIONS_ENABLED` is `True` in `development.py` and `test.py`,
and `False` in production. The gate therefore **passes in production, where it
matters**, and blocks local dry runs until you disable it:

```bash
DAWATRACE_FHIR_WRITE_INTERACTIONS_ENABLED=0 python manage.py seed_demo_scenario ...
```

That asymmetry is deliberate. Loosening the gate to make local runs convenient
would remove the check from the one environment that needs it.
