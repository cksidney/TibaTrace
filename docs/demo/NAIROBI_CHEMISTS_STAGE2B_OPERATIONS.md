# Stage 2B.1 — Operations

## Prerequisites

Stage 2A must have run against the tenant: Stage 2B.1 orders from the suppliers,
agreements and SKUs it created. The global medicine catalogue must be loaded
(`seed_medicine_catalogue`), or Stage 2A produces no SKUs and 2B.1 defers.

## Running it

```bash
python manage.py seed_demo_scenario --tenant-slug=nrbchem --profile=nairobi-chemists-pilot --stage=procurement-receiving --random-seed=83492011 --as-of-date=2026-08-03 --scale=large --allow-demo-seed
```

Locally you also need `DAWATRACE_FHIR_WRITE_INTERACTIONS_ENABLED=0`; dev and
test settings enable outbound FHIR writes, production does not.

| Flag | Effect |
|---|---|
| `--stage=procurement-receiving` | Run Stage 2B.1 |
| `--resume` | Continue from the last completed stage |
| `--from-stage=<M1..N4>` | First stage to run |
| `--stop-after-stage=<M1..N4>` | Last stage to run |
| `--manifest-digest=<sha256>` | Refuses if the computed plan differs |
| `--progress-format=text\|json` | Progress output |

Stage 2B.1 rehydrates Stage 2A's handles before its first stage, so sites,
users, suppliers and SKUs are available without re-running 2A.

## Resume

Each of the eight stages checkpoints independently. On failure the run records
the stage, its last key, the error class and the detail.

```bash
python manage.py seed_demo_scenario --tenant-slug=nrbchem --stage=procurement-receiving --random-seed=83492011 --as-of-date=2026-08-03 --resume --allow-demo-seed
```

Completed stages are **rehydrated**, not re-run. Re-running one would repeat
approvals, revisions and sends, none of which are idempotent.

Verified: interrupting at N3 leaves M1–N1 `COMPLETED` and N3 `FAILED` with
`error_class=RuntimeError`; resuming rehydrates six stages, executes two, and
adds no revisions and no batches beyond the original run.

## What this stage will not do

Refuses, by construction:

- quality release (`release_batch`)
- `InventoryReceiptService.post_receipt`
- any inventory ledger entry
- any `InventoryBalance` row
- FEFO, transfers, expiry processing, stocktake, recall, dispensing

N4 raises if any received batch is `RELEASED` or is not fully held, so a run
that crossed the boundary fails rather than completing quietly.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Requisitions created, zero orders | Supplier qualifications not valid at the order date — check `PROCUREMENT_WINDOW_DAYS` against Stage 2A's window |
| `procurement_blocked_on_supplier` high | Suppliers suspended, unqualified, or the requisition already partly ordered |
| Orders stuck at `SUBMITTED` | A revision reset approval and re-approval did not run |
| Zero SKUs | Stage 2A did not run, or the global catalogue is not loaded |
| `X batch(es) are RELEASED` | Something crossed into Stage 2B.2; the boundary assertion fired |
