# Kenya eTCD — Import Lifecycle

Two stages, with a hard boundary between them. **Stage A never activates
anything.** Everything that changes what a pharmacy can dispense happens in
Stage B, behind a reviewer.

---

## Pipeline

```
eTCD source file
  └─ CatalogueImport            file digest, source version, published date, operator
     └─ CatalogueSourceRecord   raw row, immutable, own digest
        └─ normalization        versioned contract; refuses ambiguity
           └─ substance         BLOCKED (no name in source)
           └─ dose form         vocabulary map, versioned
           └─ route             vocabulary map, versioned
           └─ strength          parser; ambiguity → review, never a guess
           └─ manufacturer      resolution; never fuzzy-matched
              └─ CatalogueMappingCandidate   tier + confidence + evidence
                 └─ [STAGE BOUNDARY — reviewer]
                    └─ CatalogueCrosswalk    immutable, supersedable
                       └─ canonical target   activated only when complete
```

Every stage carries forward: source identifier, source version, publication
date, import date, raw-source digest, normalization contract version, mapping
confidence, review state, reviewer. The original row is never discarded.

---

## States

| State | Meaning | Next |
|---|---|---|
| `UNPROCESSED` | Row ingested, untouched | `NORMALIZED`, `IMPORT_FAILED` |
| `NORMALIZED` | Parsed against a known contract version | `AUTO_MATCHED`, `REVIEW_REQUIRED` |
| `AUTO_MATCHED` | Tier 1–2 match on an identifier | `APPROVED`, `REVIEW_REQUIRED` |
| `REVIEW_REQUIRED` | Ambiguous, or tier 5–6 | `APPROVED`, `REJECTED` |
| `APPROVED` | Reviewer accepted; crosswalk written | `SUPERSEDED` |
| `REJECTED` | Reviewer declined; reason recorded | `SUPERSEDED` |
| `SUPERSEDED` | A newer source version replaced it | terminal |
| `IMPORT_FAILED` | Row unusable; quarantined with reason | terminal |

`APPROVED` and `REJECTED` are **not** terminal in the sense of being erasable —
they are superseded, never overwritten. Prior mappings stay queryable because a
dispense that happened under an old mapping must remain explicable.

---

## Stage A — candidate creation

Normalize, match, propose. Specifically **not** permitted:

- creating an active `ClinicalMedicinalProduct` or `CommercialSKU`
- writing any `BranchAssortment` row
- creating stock, batches, balances or ledger entries
- activating CDS for any product
- assigning a PPB identifier that is duplicated in the source (715 rows)
- inferring a missing value

Output is a review queue plus an evidence trail. Nothing a pharmacist can act on.

## Stage B — governed publication

Per approved candidate:

1. Reviewer approves, with a reason recorded.
2. The target hierarchy is checked complete for the depth being published.
3. Regulatory validation: fail closed on suspended or withdrawn.
4. Identifier validation: uniqueness, and GTIN check digits where present.
5. Duplicate check against existing canonical products.
6. Activation through the domain's own service — never direct ORM.
7. Audit event emitted.

**Publication depth is capped by data completeness:**

| Target | Publishable from eTCD |
|---|---|
| `ClinicalMedicinalProduct` | yes, without composition, and **not** CDS-active |
| `ManufacturedMedicinalProduct` | yes, once the manufacturer is resolved |
| `IngredientComposition` | **no** — source has no substance name |
| `PackageDefinition` | **no** — source has no pack data |
| `CommercialSKU` | **no** — requires a package |
| `BranchAssortment` | **never by import**, at any depth |

A clinical product may be accepted while its packaging is unresolved. No SKU
may become active without a valid package definition.

---

## Regulatory truth labels

An imported snapshot is not live regulator status, and must never be recorded
as though it were.

| Label | Meaning |
|---|---|
| `SNAPSHOT_IMPORTED_STALENESS_GOVERNED` | Present in an imported file; staleness tracked |
| `CURRENTLY_VERIFIED` | Confirmed against the live register within the freshness window |
| `STALE` | Snapshot older than the freshness window |
| `SUSPENDED` | Regulator suspension recorded |
| `WITHDRAWN` | Regulator withdrawal recorded |
| `UNKNOWN` | No regulatory position established |
| `MATCH_REQUIRES_REVIEW` | Mapping unresolved; no regulatory claim made |

Activation fails closed on `SUSPENDED`, `WITHDRAWN` and `UNKNOWN`. Source
presence, registration status, market authorisation, suspension, withdrawal,
expiry and last-verification are recorded **separately** — a row appearing in
the file says nothing about whether it is currently authorised.

---

## Reimport and source versions

**Same source version.** Idempotent. No duplicate source records, crosswalks,
clinical products, manufactured products, packages or SKUs. Matching on
`(source, source_identifier, source_digest)`.

**Newer source version.** Compare, do not overwrite:

1. New `CatalogueImport`, new `CatalogueSourceRecord` rows with new digests.
2. Field-level diff against the prior version.
3. Unchanged rows: prior crosswalk carries forward, no new decision.
4. Changed rows: prior crosswalk `SUPERSEDED`, new candidate raised.
5. **Material** changes — strength, form, route, substance, regulatory status —
   are flagged for review even where a crosswalk already exists.
6. Rows absent from the new file are flagged, never auto-withdrawn: absence
   from a file is not a withdrawal decision.

An active product is never silently changed. If a source revision alters the
strength of a product that pharmacies are dispensing, that is a review item,
not an update.
