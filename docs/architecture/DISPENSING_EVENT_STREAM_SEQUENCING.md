# Dispensing event stream — sequencing limitation

**Design note. Nothing here is implemented.**

The dispensing replay engine reconstructs episode state from `AuditEvent` rows.
That works, and after the tenant-scope fix it is safe. It is not a full event
store, and the gap matters enough to write down before anything depends on it.

---

## What exists

`AuditEvent` carries: `tenant`, `actor`, `action`, `model_name`, `object_id`,
`correlation_id`, `outcome`, `metadata`, plus `created_at` from
`TimestampedModel`. It is immutable (`save` raises on update) and undeletable
(`delete` raises), and it refuses a missing tenant.

Replay reads `(tenant_id, model_name="DispensingEpisode", object_id)` ordered by
`(created_at, id)`.

## What is therefore provable — and what is not

| Property | Status |
|---|---|
| One tenant per aggregate | **Provable** — non-null FK plus explicit scope |
| Events immutable | **Provable** — enforced by the model |
| Events undeletable | **Provable** — enforced by the model |
| Deterministic replay order | **Provable** — `(created_at, id)` breaks ties |
| **No gaps in the stream** | **Not provable** |
| **No duplicate sequence** | **Not provable** |
| **Optimistic concurrency by version** | **Not possible** |

There is no per-aggregate sequence number. `created_at` is a wall-clock
timestamp: several events written inside one transaction share it, which is why
ordering falls back to `id`. That gives a *stable* order, not a *meaningful*
one — `id` is a UUID, so the tiebreak is arbitrary rather than causal.

The distinction that matters: **a stream missing its middle third replays
without error.** Ordering is deterministic, every row is present and valid, and
the projection produces a confident state from incomplete history. Nothing in
the current model can detect it.

## Proposed additive design

Additive only — no existing column changes, no data rewritten.

```python
aggregate_type     = models.CharField(max_length=120)     # "DispensingEpisode"
aggregate_id       = models.CharField(max_length=160)
aggregate_sequence = models.PositiveIntegerField()

class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["tenant", "aggregate_type", "aggregate_id", "aggregate_sequence"],
            name="uq_audit_aggregate_sequence",
        )
    ]
```

Append takes `expected_version`. The unique constraint makes a concurrent
double-append fail at the database rather than in application logic, which is
the only place it can be enforced reliably.

### Migration

Three steps, each separately reversible:

1. Add the three columns nullable, no constraint. Nothing reads them.
2. Backfill per aggregate, ordered by `(created_at, id)` — the same order replay
   already uses, so the backfill cannot reorder history.
3. Add the unique constraint, and only then begin writing sequences on append.

The constraint must come **after** the backfill. Adding it first fails on every
aggregate holding more than one event with a null sequence.

### Concurrency

`aggregate_sequence` gives optimistic concurrency: an appender reads the current
version, writes `version + 1`, and loses the race to a unique-violation rather
than silently interleaving. That is stronger than row locking because it needs
no lock held across the read-decide-write window.

### Backfill honesty

A backfilled sequence proves ordering, **not continuity**. It numbers the events
that survived; it cannot show whether any were never written. Continuity is only
provable from the point sequencing goes live, and the note should stay in the
model docstring so nobody later reads a backfilled range as evidence of a
complete stream.

## Until then

Do not claim event-stream continuity. Replay gives a deterministic
reconstruction of *recorded* events, which is not the same as a complete
history, and any control depending on completeness needs this design first.
