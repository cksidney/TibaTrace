# Partial Release and Quality Decision — Architecture Decision Required

Assessment only. No lifecycle change made.

Two questions, and the second one blocks Stage 2B.2A.

---

## Part 1 — The quality service cannot express per-batch decisions

Stage 2B.2A asks for one governed inspection and one decision per received
batch, across seven outcomes, with no quantity movement. The domain supports
none of those three things together.

### 1.1 `record_inspection` is per-receipt, not per-batch

```python
QualityService.record_inspection(goods_receipt=..., inspector=..., decision=...)
```

It loops **every batch under the receipt** and applies one decision to all of
them. With 107 batches across 12 receipts, the finest granularity available is
12 blanket decisions. "Every batch has exactly one inspection, with its own
outcome" is not representable.

### 1.2 `REJECT` and `DESTROY` move quantity

```python
elif decision == ReceivingInspection.Decision.REJECT:
    batch.quality_status = REJECTED
    batch.rejected_quantity = batch.received_quantity
    batch.quarantined_quantity = 0
```

The same brief requires `quarantined_quantity == received_quantity` for all 107
batches at the endpoint. The REJECT outcome (3–6 batches) therefore cannot be
recorded through the only inspection service without breaking the boundary.

### 1.3 `release_quarantined_batch` releases

Despite recording a `QualityDecision`, it also does:

```python
batch.quality_status = ReceivedBatch.QualityStatus.RELEASED
batch.save()
```

**Do not rely on the name.** It is the *only* `QualityDecision` creation path in
the repository — one call site — and it is explicitly forbidden by this
increment. There is no way to record a quality decision without releasing.

### 1.4 Four of seven outcomes have no native state

`ReceivingInspection.Decision` offers RELEASE, QUARANTINE, REJECT,
HOLD_FOR_INVESTIGATION, DESTROY. There is no DAMAGE_HOLD, DOCUMENTATION_HOLD or
NEAR_EXPIRY_HOLD, and TEMPERATURE_EXCURSION is a boolean flag on the batch
rather than a decision.

### 1.5 Segregation of duties

`record_inspection` requires a named inspector but does **not** check the
inspector against the receipt's `received_by`. `release_quarantined_batch`
takes `decision_by` and checks nothing. Neither enforces separation. This
matches the gaps already closed for requisitions, purchase orders and supplier
qualifications, and would be fixed the same way.

### 1.6 What is needed

A `BatchQualityDecisionService` that records a per-batch decision **without**
moving quantity or changing `quality_status` to RELEASED:

```
record_decision(batch, inspector, decision_by, outcome, reason, evidence)
```

with outcomes covering the seven states, refusing self-review, and leaving the
batch fully quarantined. Release stays a separate act in Stage 2B.2B.

Whether that means new enum values, a new model, or a `hold_reason` column on
`ReceivedBatch` is the decision to take. It is additive either way.

---

## Part 2 — Partial release

The interaction, as it stands:

- `release_batch(batch, quantity=N)` moves N from quarantined to accepted.
- A partial release leaves `quality_status` at **QUARANTINED** — deliberately,
  because the remainder still is.
- `post_receipt` refuses anything not **RELEASED**.

So a partially released batch has accepted units that can never be posted. The
quantity is accepted, invisible to inventory, and stuck.

### The six questions

**1. Is partial quality release intended?**
Yes, and it must be. A pallet arriving with three crushed cartons is the normal
case; refusing the whole delivery to avoid modelling it would be worse. The
quantity fields (`accepted`, `quarantined`, `rejected`) exist precisely to
express it, so the model already assumes partial outcomes.

**2. Should posting accept quantity from a still-quarantined batch?**
No. "Quarantined" would then no longer mean "not available", and every reader
of `quality_status` would need to also read three quantity fields to know what
is true. The status must remain the single answer.

**3. Should partial acceptance create a separate inventory batch or sub-lot?**
**No — this is the option to avoid.** A sub-lot splits one manufacturer batch
into two identities. A recall arrives naming the manufacturer's batch number,
and the search would have to find both and prove it found all of them.
Traceability is the whole point of batch tracking, and splitting identity to
solve a status problem trades a modelling inconvenience for a patient-safety
one.

**4. Should `release_batch` move to a PARTIALLY_RELEASED state?**
**Yes. This is the recommendation.** It is additive to
`ReceivedBatch.QualityStatus`, it is honest — the batch genuinely is partly
released — and it keeps one row per manufacturer batch. Existing readers that
check `== RELEASED` continue to exclude it, which is the safe default, and
`post_receipt` can then opt in explicitly.

**5. Should `post_receipt` post accepted quantity independently of status?**
Only for `RELEASED` and the new `PARTIALLY_RELEASED`, and only the accepted
quantity. Not "independently of status" — that would post rejected stock the
day someone sets `accepted_quantity` by mistake.

**6. Effects.**

| Area | Effect |
|---|---|
| Traceability | Improved. One row per manufacturer batch; a recall finds one record. |
| Recalls | Unchanged lookup; quarantined remainder is already unavailable. |
| Cost | Unit cost is per batch, so a part-posting carries the same unit cost. No apportionment needed. |
| FEFO | Unaffected: FEFO reads `InventoryBatch` and available balance, and only posted quantity reaches those. |
| Reporting | "Received but not available" becomes answerable, which it currently is not. |

### Recommendation

1. Add `PARTIALLY_RELEASED` to `ReceivedBatch.QualityStatus` (additive).
2. `release_batch` sets it when `accepted > 0` and `quarantined > 0`.
3. `post_receipt` accepts `RELEASED` and `PARTIALLY_RELEASED`, posting the
   accepted quantity only.
4. Do **not** split batches into sub-lots.
5. Add `BatchQualityDecisionService` (Part 1) so a decision can be recorded
   without release.

Items 1–3 are Stage 2B.2B. Item 5 blocks Stage 2B.2A.

**Both need approval before implementation.**
