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

## Not delivered in this increment

Stated plainly rather than omitted.

| Item | Status |
|---|---|
| **N2 — scan-based receiving session** | Not implemented. `ReceivingService.open_receiving_session` / `record_scan` / `post_goods_receipt_note` exist and are the authoritative path, but `post_goods_receipt_note` posts a GRN into inventory, which crosses this increment's boundary. Wiring it needs a scan path that stops short of posting. |
| **`STAGE2B_*.json` artefacts** | Not written. The orchestrator emits the six `MASTER_DATA_*.json` files; renaming them per stage set is straightforward but was not done. Counts above come from direct measurement. |
| **`validate_demo_scenario` extension** | Not extended for 2B.1. The boundary and coherence checks exist as tests rather than as validator findings. |

None of these affect the data the increment generates or the boundary it holds.
