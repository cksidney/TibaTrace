# Stage 2B.1 — Procurement and Receiving Architecture

Generates the paper trail that stock arrives through, and **stops at
quarantined batches**.

```
Requisition → submit → approve → Purchase Order → approve → revise → re-approve
→ send → Goods Receipt → batch capture → close
                                          │
                          ════════════════╪════════════════  STAGE 2B.1 ENDS
                                          │
                    quality release → post_receipt → ledger → balance → FEFO
```

Nothing below that line runs. Received stock is not available stock, and the
step that makes it available is a separate decision by a different person. A
generator that crossed the line would create available-to-promise inventory
that no quality release authorised.

---

## Stages

Eight independently resumable stages, not two. Approvals, revisions, sends and
batch capture are **not idempotent** — resuming into the middle of a coarse
stage would repeat them, so each transition carries its own checkpoint.

| | Stage | Service |
|---|---|---|
| M1 | Purchase requisitions | `ProcurementService.create_requisition` / `add_line` |
| M2 | Submission and approval | `submit_requisition` / `approve_requisition` |
| M3 | Purchase orders | `create_priced_po_from_requisition` |
| M4 | Order approval | `approve_purchase_order` |
| M5 | Revision and release | `revise_purchase_order` / `send_po` |
| N1 | Goods receipt headers | `GoodsReceivingService.start_goods_receipt` |
| N2 | Scan session (unposted) | `ReceivingService.open_receiving_session` / `record_scan` |
| N3 | Batch capture | `receive_batch` |
| N4 | Receipt closure + boundary assertion | `close_goods_receipt` |

N2 runs the authoritative scan path and stops: `post_goods_receipt_note` posts
a GRN into inventory, so it is not called, and the session is left `ACTIVE`.

---

## Three domain rules that shaped the design

Found by running the generator, not by reading the services.

**A requisition yields exactly one purchase order.**
`create_priced_po_from_requisition` requires an `APPROVED` requisition, and
raising the first order moves it to `PARTIALLY_ORDERED`. A requisition spanning
several suppliers therefore has every supplier after the first refused. So a
requisition targets **one supplier** and draws its lines from that supplier's
agreements — which is also what a replenishment cycle looks like.

**A revision resets approval.** `revise_purchase_order` returns the order to
`SUBMITTED`, because the approval covered the version that was superseded. The
generator re-approves. That is the point of the reset, not an obstacle to it.

**Orders must be dated inside the supplier qualification window.** Stage 2A
dates qualifications from as-of minus 200 days. The first attempt raised orders
250 days back and had 57 of 80 lines correctly refused by governance. The
procurement window is now bounded at 170 days.

---

## Boundary enforcement

N4 asserts the boundary rather than trusting it, on **quantity, not status**:

```python
ReceivedBatch.all_objects.filter(tenant=...).exclude(
    quarantined_quantity=F("received_quantity")
)
```

`capture_batch` leaves `quality_status` at `PENDING_INSPECTION` and quarantines
the whole delivery. That pairing is this repository's "held on arrival"; the
`QUARANTINED` enum value is for an explicit later quality decision. Asserting
on `quality_status` alone would pass a batch whose units had been released.

---

## Determinism

Every value derives from SHA-256 over `(seed, key)`, with independent RNG
streams per domain. Related managers are read through `all_objects` with an
explicit tenant filter: `requisition.lines`, `order.lines` and
`order.revisions` are tenant-strict and return nothing outside a request, which
silently produced an empty requisition that ordered nothing.

Verified: identical rerun produces the same batch numbers, quantities and
expiry dates, and creates zero new rows.
