# Legacy `Medicine` Model — Disposition

**Recommendation: retain as source-staging and clinical-identity, and build an
explicit crosswalk to the canonical chain. Do not migrate or drop it now.**

---

## Why this is not a simple deprecation

`Medicine` is not dead code. It is load-bearing for the clinical path, while
`CommercialSKU` is load-bearing for the commercial path, and **nothing links
them**.

| Consumer | Field | On delete |
|---|---|---|
| `prescription.PrescriptionLine` | `canonical_medicine` | `PROTECT` |
| `prescription` (substitution) | `substituted_medicine` | `PROTECT` |
| `prescription` (substitution) | `substitute_medicine` | `PROTECT` |
| `cds` | `ingredient_links.medicine` | `CASCADE` |
| `patients` | allergy `medicine` | `PROTECT` |
| `medicines.MedicineIdentifier` | `medicine` | `CASCADE` |
| `medicines.TenantCatalogueProduct` | `master_medicine` | `PROTECT` |

Also consumed by `fhir/converters/medication.py`, `fhir/services/medication.py`,
`insurance/services/lifecycle.py`, `notifications`, and the dispensing engine.

`CommercialSKU` has 40 foreign keys across sales, inventory, procurement,
pricing and insurance.

So a prescription and the dispense satisfying it reference two unrelated
product identities. That is the real defect, and it exists today independently
of eTCD.

---

## Options

| Option | Assessment |
|---|---|
| **(a) Migrate into canonical and drop** | **Rejected now.** Every `PROTECT` FK is clinical history. Rewriting `canonical_medicine` on historical prescription lines re-states what was prescribed — a clinical record change, not a refactor. Viable only after canonical coverage exceeds prescribing usage. |
| **(b) Source-staging + crosswalk** | **Recommended.** Additive. `Medicine` keeps clinical identity and prescribing history; `CommercialSKU` keeps commercial identity; a crosswalk makes the relationship explicit and queryable. Nothing is rewritten. |
| **(c) Compatibility projection** | Premature. Canonical holds 47 clinical products against `Medicine`'s 11,467. A projection would be empty for 99.6% of prescribing history. |
| **(d) Read-only, no action** | Leaves two authoritative catalogues permanently, with no way to answer "was the thing dispensed the thing prescribed?" Rejected. |

---

## Recommended path

**Now** — declare the split explicitly in code and docs:
`Medicine` = clinical identity and national-catalogue staging;
`CommercialSKU` = commercial and physical identity.
Two models, one authoritative each, related by crosswalk. Not two authoritative
catalogues of the same thing.

**Next** — build `MedicineCanonicalCrosswalk` (`Medicine` ↔
`ClinicalMedicinalProduct`), immutable and supersedable, populated by review.
This is the piece that makes prescribe-versus-dispense answerable.

**Later, conditional** — once canonical coverage exceeds prescribing usage
*and* a pack-data source exists, migrate `PrescriptionLine.canonical_medicine`
to point at `ClinicalMedicinalProduct` behind the crosswalk, then retire
`Medicine` writes. Reads stay for history.

**Never** — delete `Medicine` rows. They are referenced by dispensed
prescriptions.

---

## Compatibility impact of the recommended path

| Area | Impact |
|---|---|
| Prescribing / dispensing | none — `Medicine` unchanged |
| CDS | none now; improves when compositions exist |
| FHIR `Medication` | none — converters keep reading `Medicine` |
| Procurement / inventory / pricing | none — already on `CommercialSKU` |
| Reports | new join available; none required |
| Migrations | additive only (one crosswalk table) |

The risk of the recommended path is that the split becomes permanent by
inertia. The mitigation is that the crosswalk makes the gap **measurable** —
coverage becomes a number somebody can be accountable for, rather than an
architectural fact nobody is tracking.
