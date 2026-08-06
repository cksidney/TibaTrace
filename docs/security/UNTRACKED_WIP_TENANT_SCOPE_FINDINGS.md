# Open tenant-scope finding — untracked WIP

Recorded, not fixed. The file is untracked work in progress in another tree and
is not this increment's to change.

---

## `dispensing_event_sourcing.py` — unscoped audit read

| | |
|---|---|
| Path | `backend/apps/prescription/services/dispensing_event_sourcing.py` |
| Line | 53 |
| Call | `AuditEvent.objects.filter(...)` |
| Ownership | **UNTRACKED_WIP** — present in the `feature/demo-scenario-engine-stage2d` working tree, not committed |
| Detected by | `TestServiceCodeDoesNotReadThroughTheStrictManager::test_no_unscoped_service_layer_reads` |
| Severity | Silent wrong answer, not a crash |

### Why it matters

`AuditEvent.objects` is the tenant-strict manager. It filters on thread-local
tenant context, and outside a request nothing sets that context — a management
command, a Celery task, an event-sourcing replay. The queryset then returns
**empty** and raises nothing.

For event sourcing specifically, an empty read is worse than an error. A replay
that finds no prior events concludes the aggregate has no history and rebuilds
it from nothing. The failure looks like a clean state rather than a lost one.

### Required pattern

```python
AuditEvent.all_objects.filter(tenant_id=<explicit tenant>, ...)
```

`all_objects` because the read must work outside a request, and an explicit
`tenant_id` because `all_objects` is unscoped — one without the other is a
different defect.

### Why it was not changed here

The file is untracked WIP owned by the Stage 2D work. Modifying it would edit
someone's in-progress change from an unrelated increment, and the fix cannot be
validated without the rest of that work.

**It must be fixed before that WIP is committed.** The widened service-layer
audit will fail on it, which is the intended behaviour.

### Note on the audit result

`test_no_unscoped_service_layer_reads` **passes** in a clean worktree from
`afee83a`, because the file does not exist there. It fails in the Stage 2D
working tree. That difference is the audit working correctly, not a flaky test.
