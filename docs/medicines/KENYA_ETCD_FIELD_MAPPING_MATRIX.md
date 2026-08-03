# Kenya eTCD — Field Mapping Matrix

Every field the source carries, measured against 11,467 imported records.

**Confidence** is how safely the field can drive an automated decision:
*HIGH* may match automatically, *MEDIUM* may propose a candidate, *LOW* is
evidence for a human only.

---

## Source fields (22)

| # | Source field | Meaning | Type | Req. | Example | Target concept | Conf. | Transformation | Known ambiguity |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `etcd_product_id` | National product identity | string | **yes** | `ET1099` | `CatalogueSourceRecord.source_identifier`; `Medicine.code` | **HIGH** | none | none — 0 duplicates in 11,467 |
| 2 | `ppb_registration_code` | PPB register reference | string | no (1% missing) | `CTD1234` | Regulatory identifier | **HIGH** when unique | uniqueness check | 252 groups / 715 rows duplicated — not assignable |
| 3 | `generic_concept_id` | eTCD generic concept key | int | yes | `1024` | Clinical grouping key | **HIGH** | none | vocabulary is eTCD-internal |
| 4 | `generic_concept_code` | Generic concept code | string | yes | `GE11024` | Clinical grouping key | **HIGH** | none | none |
| 5 | `generic_display_name` | Full generic description | string | yes | `Olopatadine 0.2 %w/v Ophthalmic Solution` | Evidence for review | **MEDIUM** | none | conflates strength + form + route |
| 6 | `generic_name` | Generic name | string | yes | `Olopatadine` | `ClinicalMedicinalProduct.canonical_name` (part) | **MEDIUM** | trim, case-fold | 866 duplicate groups — never sufficient alone |
| 7 | `active_component_id` | Substance key | int | yes | `1735` | `ActiveSubstance` (key only) | **LOW** | — | **no name in source** |
| 8 | `active_component_code` | Substance code | string | yes | `AC11735` | `ActiveSubstance.code` | **LOW** | — | **no name — blocks `ActiveSubstance` creation** |
| 9 | `brand_name` | Brand | string | yes | `Patanol` | `ManufacturedMedicinalProduct.brand_name` | **LOW** | trim | 2,392 duplicate groups; never clinical identity |
| 10 | `brand_display_name` | Brand description | string | yes | — | Evidence for review | **LOW** | none | free text |
| 11 | `form_id` | Dose form key | int | yes | `424` | `DoseForm` | **MEDIUM** | vocabulary map | 36 distinct → must map to `DoseForm` |
| 12 | `form_code` | Dose form code | string | yes | `DF10424` | `DoseForm.code` | **MEDIUM** | vocabulary map | eTCD codes ≠ TibaTrace codes |
| 13 | `form_description` | Dose form name | string | yes | `Solution` | `DoseForm.name` | **MEDIUM** | vocabulary map | `Solution` alone omits route |
| 14 | `route_id` | Route key | int | yes | `24` | `AdministrationRoute` | **MEDIUM** | vocabulary map | 20 distinct |
| 15 | `route_code` | Route code | string | yes | `RT10024` | `AdministrationRoute.code` | **MEDIUM** | vocabulary map | codes differ |
| 16 | `route_description` | Route name | string | yes | `Ophthalmic` | `AdministrationRoute.name` | **MEDIUM** | vocabulary map | none |
| 17 | `strength_amount` | Strength value | string | yes | `600/300` | `IngredientComposition.numerator_value` | **MEDIUM** | parse | compound vs concentration — 36 ambiguous |
| 18 | `strength_unit` | Strength unit | string | yes | `mg/mg` | `IngredientComposition.numerator_unit` | **MEDIUM** | parse | `%w/w`, `%w/v` need separate handling (888 rows) |
| 19 | `manufacture_name` | Manufacturer | string | no (815 blank) | `HARLEYS LTD-NAIROBI` | `Manufacturer` | **LOW** | resolution | 226 free-text strings, no codes |
| 20 | `keml_status` | On essential list | `Yes`/`No` | no | `Yes` | Formulary metadata | **HIGH** | none | 4,469 rows `UNKNOWN` |
| 21 | `level_of_use` | KEML facility level | `1`–`6`,`9` | yes | `4` | Formulary metadata | **HIGH** | none | none |
| 22 | `updation_date` | Source publication | ISO datetime | yes | `2024-03-11T…` | `CatalogueImport.source_published_at` | **HIGH** | ISO parse | row-level, not file-level |

---

## Fields the target needs that the source does not have

These are the reason the bridge stops where it does.

| Target field | Model | Source | Consequence |
|---|---|---|---|
| `canonical_name` | `ActiveSubstance` | **absent** | Cannot create substances → cannot create `IngredientComposition` → **CDS blind** |
| pack count / size | `PackageDefinition` | **absent** | Cannot create packages → **cannot create any `CommercialSKU`** |
| container type | `PackageDefinition` | **absent** | as above |
| `unit_of_measure` | `PackageDefinition` | **absent** | as above |
| GTIN / barcode | `ProductIdentifier` | **absent** (100%) | No scanning, no GS1 verification |
| `controlled_classification` | `ClinicalMedicinalProduct` | **absent** | Controlled-drug handling cannot be derived; must default to a **safe unknown**, never `NONE` |
| `prescription_classification` | `ClinicalMedicinalProduct` | **absent** | OTC/POM cannot be derived |
| therapeutic class / ATC | `TherapeuticClassification` | **absent** (100%) | No class-based reporting or substitution grouping |
| `market_authorisation_number` | `ManufacturedMedicinalProduct` | partial | PPB code is a register reference, not an MA number |
| registration status / expiry | regulatory | **absent** | Snapshot cannot assert current authorisation |

> **`controlled_classification` deserves emphasis.** The model default is
> `NONE`. Importing 11,467 products that silently default to "not controlled"
> would make every controlled medicine in the national catalogue appear
> unrestricted. Any bridge must set an explicit `UNKNOWN`-equivalent and refuse
> activation until a steward classifies it.

---

## Vocabulary mapping required

| Vocabulary | Source distinct | Target rows today | Action |
|---|---|---|---|
| Dose forms | 36 | 10 | Map 36 → canonical set; unmapped values route to review |
| Routes | 20 | 10 | Map 20 → canonical set |
| Manufacturers | 226 strings (815 rows blank) | 10 global | Human resolution; never fuzzy-matched |
| Active substances | 11,467 rows, codes only | 20 | **Blocked** — no names |

Vocabulary maps must be **versioned data, not code**, and the version recorded
on every crosswalk. A silent change to the form map would reclassify products
already dispensed against.
