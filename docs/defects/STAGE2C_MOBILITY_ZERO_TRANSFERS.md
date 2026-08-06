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

1. Run Stage 2C generation directly against a disposable tenant and print the
   planner's candidate count **before** filtering. Zero candidates points at 1
   or 3; non-zero candidates surviving to zero plans points at 2.
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
