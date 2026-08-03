# Stage 2B.1 — Validation

## Test evidence

19 focused tests in `backend/tests/test_demo_stage2b_procurement.py`.

| Area | Covered |
|---|---|
| Boundary | zero ledger entries, zero balances, zero inventory batches; every batch fully held; N4 refuses closure if anything was released |
| Volumes | all five counts asserted inside their authorised bands |
| Lineage | every order derives from a requisition; orders reach a received state |
| Revisions | recorded with reason and prior snapshot; re-approved, never shipped on the superseded approval |
| Delivery notes | unique per supplier |
| Quantities | delivered never exceeds ordered |
| Dates | manufacture precedes expiry; quantities positive |
| Governance | unqualified supplier refused; requester cannot approve own requisition; **order raiser cannot approve own order** |
| Ownership | every object demo-owned with an external reference and story id; batches non-resettable |
| Determinism | identical batch numbers, quantities and expiry dates across two tenants |
| Idempotency | identical rerun creates zero duplicates |
| Resume | six stages rehydrated, revisions not repeated, batches not re-captured; failed stage records error class |

## Gate results

| Gate | Result |
|---|---|
| Full backend suite | **1752 passed, 0 failed** |
| Stage 2B.1 focused | 19 passed |
| Procurement suite | 82 passed |
| Django system check | no issues |
| Migration drift | none |
| Lookup-safety audit | 0 findings |
| Tenant-manager audit | passing |
| Ruff (authoritative gate) | clean |
| Bandit | 1 Low — the documented `random.Random` in `synthetic.py`, deterministic by design |
| Secret scan | 0 findings |
| Frontend typecheck ×4 | clean |
| Frontend tests | 377 passed |
| Frontend builds | clean |
| Production | untouched |

## Defects found and fixed

Three, all pre-existing and none introduced by this increment.

**Purchase-order creator was never recorded.** `create_purchase_order` accepted
a `created_by` argument and silently dropped it — `PurchaseOrder` had no such
column. Segregation of duties on approval could not be checked at all, so one
person could raise and approve their own commercial commitment.
`approve_requisition` had enforced exactly this control for requisitions all
along. Fixed with an additive nullable column (migration 0006) and the matching
check.

**`receive_line` used the tenant-strict manager.** The purchase-order line was
locked through `PurchaseOrderLine.objects`, which returns nothing unless tenant
context is set on the thread. Outside a request — management command, Celery
task, import — the lock raised `DoesNotExist` and **took the over-receipt guard
down with it**. That guard is the only place total received quantity is checked
against the order.

**`returns_service` wrote through the same strict manager.** Works today because
tenant is passed explicitly, but depends on thread state the service never
establishes.

The existing tenant-manager audit did not catch either manager defect: it scans
views, serializers and api modules, and service code is outside its scope.
Widening it is worth considering separately.

## Validator

`ProcurementReceivingValidator` runs eleven checks and is wired into
`seed_demo_scenario --stage=procurement-receiving`:

| Check | Asserts |
|---|---|
| `tenant_ownership` | every owned object belongs to the scenario tenant |
| `orders_from_requisitions` | no orphan purchase orders |
| `order_approval_segregation` | the raiser never approved their own order |
| `supplier_qualified_at_order_date` | qualifications valid **on the order date**, not today |
| `delivery_note_uniqueness` | unique per supplier |
| `received_quantity_coherence` | delivered ≤ ordered; disposition ≤ delivered |
| `every_batch_is_held` | fully quarantined, zero accepted, none released, none orphaned |
| `batch_dates` | manufacture precedes expiry; quantity positive |
| `receiving_sessions_unposted` | no session posted |
| `no_available_stock` | zero rows across four inventory models |
| `no_duplicate_references` | no external reference used twice |

Clean run: **11 checks, 0 failures**. Four tests prove the validator *fails*
when a batch is released, an order is self-approved, or a session is posted —
a validator that only ever passes proves nothing.

## Artefacts

Six files, byte-deterministic, written to `--output-directory`:

```
STAGE2B_PROCUREMENT_MANIFEST.json
STAGE2B_RECEIVING_MANIFEST.json
STAGE2B_BATCH_SUMMARY.json
STAGE2B_VALIDATION.json
STAGE2B_COLLISIONS.json
STAGE2B_TIMINGS.json
```

Named per stage set because Stage 2A and 2B share an evidence directory and
both writing `MASTER_DATA_*.json` meant one overwrote the other.

`STAGE2B_BATCH_SUMMARY.json` carries no on-hand, available or reserved figure.
Stage 2B.1 creates no inventory, and a quantity in a batch report would read as
stock.
