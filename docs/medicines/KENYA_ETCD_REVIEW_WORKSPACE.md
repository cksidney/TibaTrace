# Catalogue Governance Workspace — Scope

An HQ workspace for the ~1,150 mapping decisions and 226 manufacturer
resolutions a first eTCD import produces. Without it, the import is a queue
nobody can work.

---

## Queues

| Queue | Est. volume | Decision |
|---|---|---|
| Unmatched records | remainder after tiers 1–2 | create candidate / reject |
| Ambiguous strengths | 924 (`%w/w`, 36 ratio, 3 unparseable) | choose interpretation / reject |
| Unresolved substances | 11,467 (codes, no names) | **blocked pending a substance dictionary** |
| Unresolved manufacturers | 226 strings + 815 blank | map to `Manufacturer` / create / reject |
| Unresolved packages | 11,467 | **blocked pending pack data** |
| Duplicate candidates | 866 generic + 2,392 brand groups | distinct product / same product |
| Regulatory conflicts | 715 duplicate PPB | resolve / omit identifier |
| Bulk high-confidence | tier 1–2 | bulk approve |

Bulk approval is available **only** for exact-identifier tiers. Anything at
tier 5 or 6 is approved one at a time, because bulk-approving a fuzzy queue is
how a reviewer approves 400 mappings they did not read.

---

## Per-record view

- Raw source row, verbatim, beside the proposed target
- Field-by-field diff, with unchanged fields de-emphasised
- Match tier, confidence, and **why** — which rule fired
- Normalization contract version applied
- Provenance timeline: file digest → import → record → candidate → decision
- Prior mappings for the same source identifier, including superseded ones
- Regulatory position and its truth label
- What activation would and would not do at this depth

The last point matters: a reviewer approving a clinical product with no
composition must see that CDS will not be active for it. Otherwise approval
reads as "this is safe to dispense", which it is not.

---

## Authorisation

| Action | Capability |
|---|---|
| View queues | `catalogue.review` |
| Approve tier 1–2 (bulk) | `catalogue.approve` |
| Approve tier 5–6 | `catalogue.approve` |
| Approve a regulatory conflict | `catalogue.regulatory.approve` |
| Publish to canonical | `catalogue.publish` |
| Run an import | `catalogue.import` |

**Segregation of duties.** The operator who ran an import may not approve
ambiguous mappings from it. Matching the pattern already used by
`SupplierQualificationService` (self-verification refused) and
`pharmacy_network.verification_service` (self-verification refused): the
service enforces it, rather than the UI hiding a button.

Bulk approval of exact-identifier matches is exempt — the decision there is
"the identifier matched", which the importer already established.

---

## Not in scope

- Editing source records. They are immutable; a correction is a new source
  version from the publisher.
- Creating clinical products by hand. That is cataloguing, not review.
- Assortment. Import never touches what a branch carries.
- Overriding a regulator status.
