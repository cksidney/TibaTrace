# DEFECT — Stage 2C mobility generates zero transfers

**Status:** open, root cause not established. Not repaired.

Four Stage 2C tests fail on positive-count assertions because the mobility
generator produces no transfers at all.

---

## Affected tests

`backend/tests/test_demo_stage2c_mobility.py`

| Test | Failure shape |
|---|---|
| `test_transfer_lifecycle_and_counts` | `assert 0 > 0` — no transfers created |
| `test_transfer_ledger_balance` | `assert Decimal('0') > 0` — no ledger movement |
| `test_stock_mobility_validator_passes` | `assert 'FAIL' == 'PASS'` |
| `test_stage2c_idempotency_and_resume` | downstream of the above |

Three other tests in the same file pass.

---

## Commits tested — identical failure at every point

| Commit | What it is | Result |
|---|---|---|
| `d6af4fa` | Stage 2D.1 readiness pipeline | **4 failed**, 3 passed |
| `afee83a` | + cold-chain dose-form fix | 4 failed |
| `f7b36a8` | + Stage 2C tenant-scope fix | 4 failed |

Run in **isolated worktrees** with no Stage 2D working-tree WIP present, so the
uncommitted work is excluded as a cause.

### What this rules out

- **Not** the cold-chain fix (`afee83a`) — fails identically before it.
- **Not** the tenant-scope fix (`f7b36a8`) — fails identically before it.
- **Not** the uncommitted Stage 2D WIP — reproduces in a clean checkout.

The failure predates all three and is reproducible from a clean checkout of
`d6af4fa`.

### The uncomfortable implication

Stage 2C was previously reported ready with passing mobility evidence. That
result **is not reproducible from a clean checkout** at any commit tested. The
earlier green run therefore depended on working-tree state that is not in
version control, or on a database that already held data. Whichever it was, the
committed code does not currently produce the evidence Stage 2C was signed off
on.

---

## Update — the defect cascades into Stage 2D.2

The 46 errors in `backend/tests/test_demo_stage2d2_hardening.py` are **the same
defect**, not a separate one. Its `hardening_ready` fixture runs the
orchestrator, which reaches Stage 2C and raises before any 2D.2 test executes:

```
tests/test_demo_stage2d2_hardening.py:93   hardening_ready
  orchestrator.py:222                      stage.run(ctx)
    stage2c.py:321                         InventoryReservationService.reserve_stock
      inventory/services.py:351            FEFOAllocationService.allocate_stock
E   ValidationError: Insufficient eligible stock. Short by 1.0000 tab.
```

Every one of the 46 is an *error at setup*, which is why they fail identically
regardless of what each test asserts.

### What this narrows

"Insufficient eligible stock" is the allocator finding nothing available to
reserve. That is **hypothesis 1** — an upstream precondition unmet — rather than
a filter defect inside the mobility planner. Stage 2C is not failing to plan
transfers; it has nothing to plan them from.

The two symptoms are one cause:

| Symptom | Reading |
|---|---|
| Stage 2C: zero transfers | nothing available to move |
| Stage 2D.2: 46 setup errors | nothing available to reserve |

### Consequence for sequencing

Stage 2D.2 cannot be developed or validated until this is fixed. Its entire
suite is blocked at fixture setup, so any 2D.2 work would be written without
test feedback.

---

## Root cause identified — stale `available` snapshot with a floor of 1

Stage 2B.2B is **not** missing. Committed `stage2b2.py` implements the whole
chain -- Q1 release plan, Q2 `release_batch`, R1 `post_receipt`, R2
`rebuild_all_balances`, S1 FEFO, S2 boundary -- and the failing fixture composes
`STAGE_2B_1 + STAGE_2B_2A + STAGE_2B_2B + STAGE_2C`, so it runs in the right
order. `PARTIALLY_RELEASED` exists on the model and `post_receipt` accepts it.
The "never entered branch history" hypothesis is refuted.

The defect is in Stage 2C's planner.

### The signature

```
ValidationError: Insufficient eligible stock. Short by 1.0000 tab.
```

**Short by one unit, not by everything.** The allocator is not finding an empty
warehouse; it is finding one unit less than the plan demands. That rules out
"no stock was ever posted" and points at a quantity the planner chose.

### The mechanism

Both planners read `bal.available` at planning time and floor the result at 1:

```python
# transfer planning
qty = max(Decimal("1"), Decimal(str(int(bal.available * Decimal("0.3")) or 1)))
# reservation planning
qty = max(Decimal("1"), Decimal(str(rnd.randint(1, min(10, int(bal.available) or 1)))))
```

`available` is captured **before any allocation runs**. Execution then consumes
it: each transfer and reservation reduces the same balances the plan was built
from. By the time a later item executes, `available` has fallen below its
planned quantity.

The `max(Decimal("1"), ...)` floor is what turns that into a hard failure rather
than a smaller transfer. A balance that has been fully consumed still plans a
quantity of **1**, and the allocator correctly reports it is short by exactly
that.

### Why this also explains the "82,900 units" report

Stock genuinely was posted. Stage 2B.2B works. The earlier figures were probably
real -- what was never reproducible was Stage 2C *consuming* them, because the
first allocation to exhaust a balance aborts the stage and every downstream
count reads zero.

### Fix direction (not implemented)

Plan against live availability rather than a snapshot: re-read `available`
immediately before each allocation, skip a balance that can no longer satisfy
the minimum, and drop the floor of 1 so an exhausted balance plans nothing
instead of planning the impossible. Preserving determinism means the skip must
be a deterministic function of the plan order, not of whatever the database
returns.

---

## Hypothesis categories

Not yet investigated. Ordered by how cheaply each can be eliminated.

1. **Upstream precondition unmet.** The generator needs available inventory to
   move. Stage 2B.2B (release and posting) may not run in the test fixture, so
   there is no balance to transfer and the planner correctly plans nothing.
2. **Planner filter excludes everything.** A tenant, branch, status or location
   filter matching zero rows — the same class of defect as the tenant-strict
   manager returning empty, which this codebase has produced repeatedly.
3. **Fixture drift.** The test fixture stopped seeding a prerequisite the
   generator depends on, without the generator noticing.
4. **Silent skip.** The stage defers or `continue`s past every candidate and
   records the shortfall only in counts nobody asserts on.

Categories 1 and 2 both produce *exactly* this signature: a clean run, no
error, zero output. A generator that plans nothing and reports success is
indistinguishable from one that is not being given anything to plan.

---

## Recommended diagnostic sequence

1. **Start here.** Assert `InventoryBalance` and `InventoryBatch` counts in the
   fixture immediately before Stage 2C runs. The 2D.2 traceback shows the
   allocator finding no eligible stock, so the question is whether Stage 2B.2B
   (quality release and `post_receipt`) ever ran to create any. If balances are
   zero, the mobility planner is behaving correctly and the defect is upstream.
2. If candidates are zero, assert on `InventoryBalance` and `InventoryBatch`
   counts in the fixture — Stage 2C cannot move stock that was never posted.
3. If candidates exist but no transfer is created, log each filter's survivor
   count in order; the one that drops to zero is the defect.
4. Check whether the stage records a deferral. If it does, the summary already
   names the cause and nothing asserts on it — which is its own defect.

Add a guard once the cause is known: the stage should **fail** rather than
complete when it plans zero transfers against a tenant that has stock, in the
same way Stage 2B.1's N4 asserts its boundary instead of trusting it.

---

## Scope

Registered during the Stage 2C tenant-scope security merge. Deliberately not
repaired there: the merge was a scoped security fix, and mixing an unrelated
generator repair into it would have made both harder to review and harder to
revert.
