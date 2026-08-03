# Nairobi Chemists — Stage 2A Master Data

Stage 2A generates the governed master data that later scenarios depend on:
the organisation, its sites and departments, storage areas, staff, prescribers,
patients, manufacturers, suppliers and insurers.

It creates **no transactional data**. No purchase orders, no batches, no ledger
entries, no prescriptions, no sales, no claims. The validator asserts this
rather than trusting it.

---

## The tenant

| | |
|---|---|
| Name | `Nairobi Chemists` |
| Slug | `nrbchem` |
| Designated demo tenant | required — `Tenant.is_demo` must be `True` |

`nairobi-chemists` is not a slug that exists. Do not use it.

---

## Scenario identity

| | |
|---|---|
| Scenario | Nairobi Chemists Enterprise Pilot |
| Scenario version | 1.0 |
| Demo version | 2026.08.03 |
| Profile | `nairobi-chemists-pilot` |
| Random seed | 83492011 |

Counts live in `apps/platform/demo/profiles.py` as `MasterDataTargets`, not in
generator code. The dry run and the real run read the same constants, so the
plan a manifest describes is the plan that executes.

---

## Stages

| | Stage | Requires |
|---|---|---|
| A | Tenant verification and scenario initialisation | — |
| B | Organisation, sites and departments | A |
| C | Inventory locations | B |
| D | Roles, users and memberships | B |
| E | Practitioners and regulatory authority | D |
| F | Patients | D |
| G | Manufacturers and catalogue selection | A |
| H | Suppliers and agreements | D |
| I | Insurers, schemes and plans | D |
| J | Price books and price entries | G |
| K | Premises and regulatory master records | E |
| L | Master-data summary and validation | A |

Each stage runs in its own transaction. The run is deliberately not wrapped in
one: a failure in stage K would otherwise roll back the ten stages before it,
which is exactly what `--resume` exists to avoid.

---

## Running it

Dry run first. The digest it prints is what an approval binds to.

```bash
python manage.py seed_demo_scenario --tenant-slug=nrbchem --profile=nairobi-chemists-pilot --random-seed=83492011 --as-of-date=2026-08-03 --dry-run --allow-demo-seed --output-manifest=/tmp/nrbchem-manifest.json
```

Then the real run, quoting the approved digest:

```bash
python manage.py seed_demo_scenario --tenant-slug=nrbchem --profile=nairobi-chemists-pilot --stage=master-data --random-seed=83492011 --as-of-date=2026-08-03 --scale=large --manifest-digest=<APPROVED-DIGEST> --allow-demo-seed
```

If the computed plan differs from the approved digest the command refuses. An
approval authorises one exact plan; a changed plan needs a new approval.

### Options

| Flag | Effect |
|---|---|
| `--stage=master-data` | Run Stage 2A. Omitting it plans only. |
| `--resume` | Continue from the last completed stage |
| `--from-stage=<A-L>` | First stage to run |
| `--stop-after-stage=<A-L>` | Last stage to run |
| `--output-directory=<path>` | Where evidence artefacts are written |
| `--progress-format=text\|json` | Progress output |
| `--manifest-digest=<sha256>` | Refuses if the plan does not match |

Locally you also need `DAWATRACE_FHIR_WRITE_INTERACTIONS_ENABLED=0`; dev and
test settings enable outbound FHIR writes, production does not.

---

## Determinism

Every value derives from SHA-256 over `(seed, key)` — not Python's `hash()`,
which is salted per process and would produce different data every run.

Each domain draws from an **independent** RNG stream. Under one shared stream,
inserting a supplier would shift every patient generated afterwards, changing
the manifest digest and invalidating an approval that had already been granted.

Verified: the same inputs produce the same manifest digest, the same patient
names and the same identifiers; artefact files are byte-identical.

---

## Idempotency and resume

Every object carries a deterministic external reference recorded in
`DemoScenarioObject`. A rerun looks objects up through that ownership registry,
not through the domain table, so a record that merely happens to share a code
is never adopted.

Collisions are classified `SAFE_REUSE`, `SAFE_UPDATE`, `OWNERSHIP_CONFLICT`,
`IDENTITY_CONFLICT`, `LIFECYCLE_CONFLICT`, `TENANT_SCOPE_CONFLICT` or
`BLOCKED`. The last five stop the run.

`--resume` **rehydrates** completed stages rather than re-running them: it
rebuilds the handles later stages need by looking them up. Re-running a
completed stage would repeat lifecycle transitions that are not idempotent — a
premises approval, a supplier approval.

Measured on a disposable tenant: first run 4.6s, identical rerun 0.2s creating
zero new rows; interruption at stage F resumed with A–E rehydrated and
validation passing.

---

## Safety properties

| Property | How |
|---|---|
| Patient identifiers | `NCD-` prefixed, non-numeric — cannot be read as a Kenyan national ID (8 digits) |
| Email | Reserved `.invalid` TLD (RFC 2606); undeliverable and unregistrable |
| Phone | Single obvious `+254700` block |
| GTIN | GS1 demonstration prefix `952`, never issued to a member company; valid check digits |
| Passwords | Guarded demo-password mechanism; never logged, never in an artefact |
| Practitioner verification | `MANUAL_INTERNAL_VERIFICATION` / `NOT_EXTERNALLY_CONNECTED` |
| Insurers | Always `SANDBOX` + `FAKE` adapter; promotion is a separate governed act |
| Departments | Grant no capabilities; the one demo ABAC policy DENYs and cannot widen |

No external registry is contacted. Nothing claims PPB, HWR, DHA, GS1 or SHA
verification.

---

## Two premises in the brief that the schema does not support

The generator follows the schema, not the brief, and records why.

**Practitioners are prescribers.** `Practitioner.profession` offers DOCTOR,
DENTIST, CLINICAL_OFFICER, NURSE_PRESCRIBER, VETERINARY_PRESCRIBER and
OTHER_AUTHORIZED_PRESCRIBER. There is no PHARMACIST. In this domain pharmacists
and technologists are `identity.User` rows carrying a role — created in stage D
— so registering them as practitioners would duplicate every one of them and
make "who dispensed this?" ambiguous.

**Premises are tenant-level.** `PharmacyProfile` is OneToOne with `Tenant`, so
a per-branch regulatory state (CBD verified, Westlands renewal-due, warehouse
pending) is not representable. One tenant holds one premises licence.

---

## Catalogue ceiling — read this before expecting 300–500 SKUs

A `CommercialSKU` is a tenant's listing of a **global** manufactured product in
a particular pack. Stage 2A lists from the global catalogue and never writes
clinical or manufactured products: inventing a clinical medicine to reach a
count would put a product into clinical decision support that no regulator
authorised.

The global catalogue in this repository (`seed_medicine_catalogue`) holds
**30 manufactured products and 3 active package definitions**, so the ceiling
is **90 SKUs**. The pilot target of 300–500 is not reachable from it.

Reaching 300–500 needs a larger real catalogue loaded first. `import_ke_etcd_catalogue`
exists and imports the Kenya eTCD product catalogue, but it populates the
legacy global `Medicine` model rather than the
ClinicalMedicinalProduct → ManufacturedMedicinalProduct → CommercialSKU chain,
so it does not feed this path today. Bridging the two is a separate,
reviewable piece of work.

Everything else in the pilot profile is met.

---

## Deferred domains

One domain remains deferred, and it is not a service gap:

| Domain | Why |
|---|---|
| `premises_profile` | `PharmacyProfile` is created by tenant onboarding (`PharmacyOnboardingService`), not by this engine. A tenant without one gets no premises record rather than a fabricated licence. |

The five service gaps from the previous increment are **closed**:

| Domain | Service now used |
|---|---|
| `medicine_assortment` | `TenantCatalogueProvisioningService`, `CatalogueSelectionService`, `BranchAssortmentProvisioningService` |
| `supplier_qualifications` | `SupplierQualificationService` |
| `supplier_product_agreements` | `SupplierProductAgreementService.provision_agreement` |
| `insurance_coverage` | `InsuranceBenefitService`, `InsuranceMembershipService` |
| `price_books` | `PriceBookService` |

---

## Artefacts

Written to `--output-directory`, or
`demo-evidence/<slug>/<demo-version>/<digest-prefix>/`:

```
MASTER_DATA_MANIFEST.json
MASTER_DATA_SUMMARY.json
MASTER_DATA_VALIDATION.json
MASTER_DATA_COLLISIONS.json
MASTER_DATA_TIMINGS.json
MASTER_DATA_KPIS.json
```

KPIs cover master-data coverage only. There is no revenue, dispensing-time or
stock-turn figure, because Stage 2A creates no transactions and any such number
would be fabricated.

---

## Validation

```bash
python manage.py seed_demo_scenario --tenant-slug=nrbchem --stage=master-data --validate-only --allow-demo-seed
```

Eleven checks, including the load-bearing one: **zero transactional objects
owned by the run**, asserted across thirteen transactional models through
scenario ownership rather than raw row counts — counting rows would fail
falsely on a tenant that legitimately contains other data.

The run is not marked complete unless every check passes.
