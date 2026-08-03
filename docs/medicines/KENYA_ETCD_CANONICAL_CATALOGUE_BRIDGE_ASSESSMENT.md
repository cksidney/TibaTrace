# Kenya eTCD → Canonical Catalogue Bridge — Assessment

**Status: design ready, source clarification required before implementation.**

Assessment only. No schema, importer or service changes were made.

---

## 1. Headline finding

The eTCD source **cannot reach `CommercialSKU`**, and it cannot reach
`IngredientComposition` either. Not because the bridge is hard to build, but
because the source does not carry the facts those models require.

Measured against the 11,467 imported records in the local development database:

| Required by target | Present in eTCD | Rows |
|---|---|---|
| Pack size / count / container | **absent** | 0 / 11,467 |
| GTIN or barcode | **absent** | 0 / 11,467 |
| ATC / therapeutic class | **absent** | 0 / 11,467 |
| Active-substance **name** | **absent** (id + code only) | 0 / 11,467 |
| Controlled-drug classification | **absent** | 0 / 11,467 |
| Prescription classification (OTC/POM) | **absent** | 0 / 11,467 |
| Registration status / expiry | **absent** (a registration *code* only) | 0 / 11,467 |

The repository already recorded this conclusion in
`docs/integrations/KE_ETCD_PRODUCT_CATALOGUE.md`: *"The source does not provide
enough structured ingredient or pack information to build a clinical
composition or commercial SKU safely."* This assessment confirms it with
numbers and establishes exactly how far the bridge **can** go.

**How far it can go:** eTCD supports `ClinicalMedicinalProduct` and
`ManufacturedMedicinalProduct` as *review candidates*. It stops there.

```
eTCD ──► ClinicalMedicinalProduct      reachable, review required
     ──► ManufacturedMedicinalProduct  reachable, manufacturer resolution required
     ──► IngredientComposition         BLOCKED: no substance name
     ──► PackageDefinition             BLOCKED: no pack data at all
     ──► CommercialSKU                 BLOCKED: requires a package
```

A SKU count of 300–500 is therefore **not** obtainable from eTCD. It requires a
commercial pack source (supplier catalogues, GS1 GTIN data, or manual
cataloguing), which is a different procurement of data, not a mapping problem.

---

## 2. Source profile — 11,467 records

All rows are `status=INACTIVE`, as the importer intends.

**Completeness**

| Field | Missing | % |
|---|---|---|
| `generic_name` | 0 | 0.0% |
| `brand_name` | 0 | 0.0% |
| `dosage_form` | 0 | 0.0% |
| `strength` | 0 | 0.0% |
| `licence_identifier` (PPB) | 111 | 1.0% |
| `gtin` | 11,467 | 100% |
| `primary_barcode` | 11,467 | 100% |
| `atc_code` | 11,467 | 100% |

**Duplication**

| Kind | Groups | Rows involved |
|---|---|---|
| Duplicate `etcd_product_id` | **0** | 0 |
| Duplicate PPB registration | 252 | 715 |
| Duplicate generic name | 866 | 11,154 |
| Duplicate brand name | 2,392 | 5,878 |

`etcd_product_id` is clean and is a sound identity anchor. Duplicate generic and
brand names are *expected* — many brands share a generic — and are precisely why
name text must never be sufficient for a match.

**Derived target volumes**

| Concept | Count |
|---|---|
| Distinct clinical identities (generic + form + route + strength) | **2,593** |
| — appearing once | 1,171 |
| — with more than one brand | 1,422 |
| Distinct manufactured-product candidates | **10,984** |
| Distinct manufacturer strings (free text) | 226 |
| Rows with no manufacturer at all | 815 |
| Distinct dose forms / routes | 36 / 20 |
| Existing `ClinicalMedicinalProduct` rows | 47 |
| Existing global `Manufacturer` rows | 10 |

**Strength expressions**

| Class | Rows | % | Example |
|---|---|---|---|
| Single value + unit | 8,197 | 71.5% | `5 mg` |
| Compound, balanced values/units | 2,379 | 20.7% | `600/300 mg/mg` |
| Ratio, other | 888 | 7.7% | `2 %w/w` |
| Unparseable | 3 | 0.0% | `75 microgram per hour` |

Of the compound rows, 2,343 have identical units (`mg/mg` — unambiguously a
combination product) and **36 have differing units** (`mg/mL`), which cannot be
distinguished from a concentration without human review. Those 36 are the
genuinely ambiguous population.

---

## 3. The problem underneath the bridge

**Two clinical catalogues already exist, and this predates eTCD.**

| Model | Consumed by | FKs |
|---|---|---|
| `Medicine` | prescribing, dispensing, substitution, CDS ingredient links, patient allergy | 6 |
| `CommercialSKU` (via `ClinicalMedicinalProduct`) | sales, inventory, procurement, pricing, insurance | 40 |

Nothing links them. `Medicine` is authoritative for *what was prescribed*;
`CommercialSKU` is authoritative for *what was sold and stocked*. A prescription
and the dispense that satisfies it therefore reference two unrelated product
identities, with no crosswalk between them.

That is the substantive architectural issue. Importing eTCD into the canonical
chain **does not solve it and would make it worse**: a third population of
product rows, related to `Medicine` only by having come from the same source
file.

**Recommendation: resolve `Medicine` ↔ `ClinicalMedicinalProduct` before, or as
part of, any eTCD bridge.** Section 7 sets out the disposition options.

---

## 4. Target-model gaps

Five target models have **no authoritative service** — they are created only by
seed commands writing directly to the ORM:

| Model | Service | Consequence for the bridge |
|---|---|---|
| `ActiveSubstance` | **none** | Cannot register substances; blocks composition |
| `DoseForm` | **none** | 36 source forms cannot be registered |
| `AdministrationRoute` | **none** | 20 source routes cannot be registered |
| `TherapeuticClassification` | **none** | No classification path (and no source data) |
| `PackageDefinition` | **none** | Blocks any SKU |
| `ClinicalMedicinalProduct` | `MedicineCatalogueService.create_clinical_product` | usable |
| `ManufacturedMedicinalProduct` | `MedicineCatalogueService.register_manufactured_product` | usable |
| `Manufacturer` | `ManufacturerRegistrationService` | usable |
| `CommercialSKU` | `TenantCatalogueProvisioningService` | usable, but needs a package |
| `BranchAssortment` | `BranchAssortmentProvisioningService` | usable |

`IngredientComposition` has `add_ingredient`, but it requires an
`ActiveSubstance`, which has no service and no source name.

**`LegacyIdentifierCrosswalk` cannot be reused.** It is already immutable
(refuses update and delete) — the right pattern — but it is *tenant-scoped*
(`tenant` required, `StrictTenantManager`). eTCD mapping is global reference
data with no tenant. A separate global crosswalk model is required.

---

## 5. Mapping tiers

Deterministic, highest confidence first. **No tier matches on name text alone.**

| Tier | Rule | Auto? | Est. rows |
|---|---|---|---|
| 1 | `etcd_product_id` already crosswalked | yes | reimport only |
| 2 | Exact PPB registration, unique in source **and** target | yes | ~10,641 eligible, 715 excluded as duplicates |
| 3 | Exact GTIN | yes | **0** (source has none) |
| 4 | Exact substance + strength + form + route + manufacturer + pack | yes | **0** (no pack, no substance name) |
| 5 | Exact clinical identity, packaging unresolved | **candidate only** | 2,593 |
| 6 | Fuzzy / anything else | **review** | remainder |

Tier 5 is where the bulk lands, and tier 5 is explicitly *not* activation — a
clinical product may be accepted while its packaging stays unresolved, but no
SKU may become active without a package.

**Never merge on:** brand-name similarity, generic-name similarity, differing
salts, differing strengths, differing dose forms, differing routes, differing
release characteristics, differing manufacturers, differing pack sizes.

---

## 6. Expected auto-match and review volume

| Outcome | Rows | Basis |
|---|---|---|
| Auto-matchable to an existing canonical product | **~0** | only 47 canonical products exist; 2,593 candidate identities |
| Clinical candidates creatable without review | 8,197 (71.5%) | single unambiguous strength, all four identity fields present |
| Strength review required | 924 | 888 `%w/w`-style + 36 ambiguous ratios + 3 unparseable |
| Compound composition review | 2,343 | balanced `mg/mg` — structure clear, but substance names absent |
| Manufacturer review | 226 distinct strings + 815 unattributed rows | free text, no codes |
| PPB identifier not assignable | 715 | duplicate registration in source |

**Realistic review queue on first import: ~1,150 mapping decisions plus 226
manufacturer resolutions**, assuming compound products are accepted structurally
and their substances deferred.

This is a multi-week catalogue-stewardship exercise, not a batch job.

---

## 7. Legacy `Medicine` disposition

Four options considered. **Recommendation: (b) source-staging + crosswalk.**

| Option | Verdict |
|---|---|
| (a) Migrate `Medicine` into canonical models and drop it | **Rejected for now.** 6 FKs including `PrescriptionLine.canonical_medicine` and CDS ingredient links, all `PROTECT`. Migration rewrites clinical history. |
| **(b) Retain as source-staging + build a crosswalk to canonical** | **Recommended.** Keeps prescribing history intact, makes the two catalogues explicitly related, and is additive. |
| (c) Compatibility projection (view over canonical) | Premature — canonical has 47 rows against `Medicine`'s 11,467. The projection would be empty. |
| (d) Leave read-only, do nothing | Leaves two authoritative catalogues permanently. Rejected. |

Under (b), `Medicine` becomes explicitly a **staging and clinical-identity**
model, `CommercialSKU` remains the **commercial identity**, and a crosswalk
records the relationship. Deprecation of `Medicine` becomes possible only once
canonical coverage exceeds prescribing usage — which is after, not before, a
pack-data source exists.

---

## 8. Proposed schema (not implemented)

All additive. Global reference data, no tenant column.

| Model | Purpose |
|---|---|
| `CatalogueSource` | A named source (KE-eTCD), its publisher and vocabulary version |
| `CatalogueImport` | One import run: file digest, source version, publication date, counts, operator |
| `CatalogueSourceRecord` | One raw source row, immutable, with its digest and normalization state |
| `CatalogueMappingCandidate` | A proposed target with match tier, confidence and evidence |
| `CatalogueCrosswalk` | The accepted mapping: source record → target object, immutable, supersedable |
| `CatalogueMappingDecision` | Reviewer, decision, reason, timestamp — append-only |

**States:** `UNPROCESSED → NORMALIZED → AUTO_MATCHED | REVIEW_REQUIRED →
APPROVED | REJECTED`, plus `SUPERSEDED` and `IMPORT_FAILED`.

Indexes required on `(source, source_identifier)`, `(target_type, target_id)`,
`(state)` and `(import_id, state)` — the review queue and the reimport
comparison both scan on these.

**Services required:** `CatalogueImportService`, `CatalogueNormalizationService`
(versioned contract), `CatalogueMatchingService`, `CatalogueReviewService`,
plus the five missing primitives (`ActiveSubstance`, `DoseForm`,
`AdministrationRoute`, `TherapeuticClassification`, `PackageDefinition`).

---

## 9. Safety risk register

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Two products merged that differ by salt or release characteristic | **Patient harm.** Wrong drug dispensed against a prescription | Tiers 1–4 only; salt/release differences never auto-merge |
| R2 | Compound parsed as concentration (36 rows) | **Patient harm.** 10× dosing error class | Ambiguous ratios always route to review |
| R3 | Canonical product created with no composition | CDS interaction and allergy checking silently blind | No CDS activation without composition; composition blocked until substance names exist |
| R4 | Imported snapshot treated as current PPB status | Dispensing a withdrawn product | Truth labels; snapshot never equals live status; fail closed on suspended/withdrawn |
| R5 | Manufacturer free-text collapsed by fuzzy match | Wrong attribution; recall scope wrong | Manufacturer resolution is always reviewed |
| R6 | SKU created without a package | Inventory in undefined units; FEFO and stock counts meaningless | No SKU without a valid `PackageDefinition` |
| R7 | Auto-assortment on import | Untriaged products dispensable at branches | Import never touches assortment |
| R8 | Duplicate PPB identifier assigned (715 rows) | Two products claiming one registration | Existing importer already omits these; preserve that |
| R9 | Reimport silently changes an active product | Price, pack or clinical facts change under live stock | Material changes supersede and flag; never mutate in place |
| R10 | Third product population created | Prescribing, dispensing and stock diverge further | Resolve `Medicine` ↔ canonical first |

---

## 10. Performance

Measured basis: 11,467 rows already imported to `Medicine` in the local
development database; that import is not the bottleneck.

| Aspect | Estimate |
|---|---|
| Normalization pass (pure function, no I/O) | < 5 s for 11,467 rows |
| Matching with prefetched target indexes | ~30–60 s; **must** preload substance/form/route/manufacturer maps into memory rather than querying per row |
| Database growth | ~11,467 source records + ~13,600 candidates ≈ 25k rows, ~2.2 KB/row ≈ **55 MB** |
| Chunk size | 500 rows per transaction |
| Resumability | Per-record state; a failed chunk resumes from `NORMALIZED` |

The rule that matters: **11,467 rows × per-row queries for substance, form,
route and manufacturer is ~46,000 queries.** Preload the vocabularies. Do not
optimise by skipping validation.

---

## 11. Implementation phases

| Phase | Content | Gate |
|---|---|---|
| **0** | Resolve `Medicine` ↔ `ClinicalMedicinalProduct` disposition | Architecture decision **required before phase 1** |
| **1** | The five missing primitive services (`ActiveSubstance`, `DoseForm`, `AdministrationRoute`, `TherapeuticClassification`, `PackageDefinition`) | Tests green; no importer changes |
| **2** | Provenance schema + immutable crosswalk models | Additive migration, declared in migration evidence |
| **3** | Versioned normalization contract (strength, form, route) | Refuses ambiguity; 36-row ambiguous set proven to route to review |
| **4** | Matching engine, tiers 1–2 and 5 only | Zero auto-activation |
| **5** | HQ review workspace | SoD enforced |
| **6** | Governed publication (Stage B) | Nothing activates without approval |
| **7** | Reimport / source-version comparison | Supersession, no silent mutation |

**Phases 1 and 2 are useful independently of eTCD** — the missing primitive
services are a gap in their own right.

---

## 12. Recommendation on timing

**Implement after the Nairobi Chemists pilot, not before.**

- Stage 2B is unblocked at 90 SKUs. The pilot demonstrates procurement,
  inventory, dispensing and claims; it does not need 11,467 products, and a
  larger catalogue would slow every pilot run without changing what is shown.
- The bridge cannot produce SKUs at all until a **pack-data source** exists.
  Building it first yields ~2,593 clinical products with no packages, no
  compositions and no SKUs — which improves no pilot scenario.
- Phase 0 is an architecture decision about clinical history. It should not be
  taken under demo-schedule pressure.

What *should* happen before the pilot: nothing in this document. What should
happen soon and independently: **phase 1**, because five domain primitives
having no service is a live gap that the demo work already had to route around.

---

## 13. Source clarification required

Before implementation can be scoped further, three questions need answers that
are not in the repository:

1. **Is a pack/GTIN source available?** Without one the bridge stops at
   manufactured product, and no SKU target is reachable. Which source, and under
   what licence?
2. **Is there an eTCD active-substance dictionary?** The product feed carries
   `active_component_id`/`code` but no name. `ActiveSubstance` requires a
   canonical name, and `IngredientComposition` requires `ActiveSubstance`. Is a
   substance reference feed published separately?
3. **Is live PPB status queryable?** `ppb_adapter.py` exists. If the register
   can be queried, registration status and expiry become derivable and the
   staleness governance in section 9 (R4) can be tightened from "snapshot" to
   "verified".

The design in this document holds regardless of the answers. The **reachable
target depth** depends entirely on question 1, and **CDS safety** on question 2.
