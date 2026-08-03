# Stage 2B.1 — Generated Counts

Measured on a disposable tenant (`s2bverify`) with Stage 2A master data and the
global catalogue loaded. Seed `83492011`, as-of `2026-08-03`.

| | Generated | Authorised band | |
|---|---|---|---|
| Purchase requisitions | **12** | 8–12 | ✅ |
| Requisition lines | 132 | — | |
| Purchase orders | **12** | 12–20 | ✅ |
| — partial orders | 4 | — | |
| PO revisions | **3** | — | |
| — re-approved after revision | 3 | — | |
| Orders sent | 12 | — | |
| Goods receipts | **12** | 10–16 | ✅ |
| Goods receipt lines | **107** | 80–140 | ✅ |
| Received batches | **107** | 100–180 | ✅ |
| Batches fully held | **107 / 107** | all | ✅ |
| Inventory ledger entries | **0** | 0 | ✅ |
| Inventory balances | **0** | 0 | ✅ |
| Inventory batches | **0** | 0 | ✅ |

**Purchase order end states:** `FULLY_RECEIVED` 7, `PARTIALLY_RECEIVED` 5.
**Batch quality status:** `PENDING_INSPECTION` 107, with
`quarantined_quantity == received_quantity` on every one.

## Configuration

Bounded constants in `apps/platform/demo/generation/stage2b.py`:

| Constant | Value | Effect |
|---|---|---|
| `REQUISITION_COUNT` | 12 | requisitions, and therefore orders and receipts |
| `LINES_PER_REQUISITION` | 11 | lines per requisition → receipt lines → batches |
| `PARTIAL_ORDER_EVERY` | 3 | every 3rd requisition is partly ordered |
| `REVISE_EVERY` | 4 | every 4th order is revised before sending |
| `PROCUREMENT_WINDOW_DAYS` | 170 | must stay inside Stage 2A's 200-day qualification window |

## Delivery shapes

Cycled deterministically across receipts: complete, partial (60%), short (85%),
damaged, temperature excursion, near-expiry, complete, rejected line. Each
carries a discrepancy reason recorded on the receipt line.

## Performance

| | |
|---|---|
| Runtime | **1.2 s** |
| Identical rerun | **0.0 s**, zero duplicates |
| Database growth | **384 KiB** |
| Demo-owned objects (2A + 2B.1) | 2,259 |
