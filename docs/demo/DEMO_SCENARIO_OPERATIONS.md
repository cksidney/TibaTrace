# Demo Scenario Engine — Operations

**Stage 1.** Planning only: designation, classification, gates, manifest. No
transactional data is generated yet, and the engine says so loudly rather than
leaving an empty tenant that looks like a success.

---

## The tenant

| | |
|---|---|
| Name | `Nairobi Chemists` |
| Slug | `nrbchem` |
| Environment | production |
| Designated demo tenant | **not yet** — see below |

`nairobi-chemists` is not a slug that exists. Do not use it.

---

## 1. Inspect before anything else

Read-only. Answers whether the tenant is empty, demo-owned, or carrying work
nobody can account for.

```bash
python manage.py inspect_demo_tenant --tenant-slug=nrbchem --tenant-id=<UUID>
```

Verdicts:

| Verdict | Meaning |
|---|---|
| `EMPTY_SAFE_TO_SEED` | nothing, or only a bootstrap user |
| `DEMO_DATA_PRESENT` | everything present is owned by a recorded demo run |
| `REAL_DATA_PRESENT` | unaccounted **transactional** records — blocks |
| `UNCLASSIFIED_DATA_PRESENT` | records nobody can attribute — blocks |
| `BLOCKED` | classification not possible |

Low row counts never imply safety. A tenant with fifteen prescriptions is a
tenant that has been used.

---

## 2. Designate the tenant (Platform Owner)

Nothing may be seeded until `is_demo` is `True`, and setting it is deliberately
awkward: id, slug and name must all match, `--confirm` must repeat the slug, and
a reason is mandatory. Every designation writes an audit event.

```bash
python manage.py designate_demo_tenant \
  --tenant-id=<EXACT-UUID> \
  --tenant-slug=nrbchem \
  --tenant-name="Nairobi Chemists" \
  --reason="Authorised demonstration tenant per <approval reference>" \
  --actor-username=<platform-owner> \
  --confirm=nrbchem
```

Reversible with `--undesignate`, audited the same way.

The actor needs `platform.demo.govern` or superuser. That capability is new in
this change and appears in the catalogue under *Platform governance*.

---

## 3. Dry run

Produces the manifest. Determinism is the point: the same tenant, profile,
version, seed and as-of date always yield the same SHA-256, and any change to
the plan changes the digest — which is what invalidates a stale approval.

```bash
python manage.py seed_demo_scenario \
  --tenant-slug=nrbchem \
  --profile=nairobi-chemists-pilot \
  --random-seed=20260802 \
  --as-of-date=2026-08-02 \
  --dry-run \
  --allow-demo-seed \
  --output-manifest=/tmp/nrbchem-manifest.json
```

Locally you will also need `DAWATRACE_FHIR_WRITE_INTERACTIONS_ENABLED=0`; dev
and test settings enable outbound FHIR writes, production does not.

---

## 4. Production execution — not yet possible

Stage 1 has no generator. When Stage 2 lands, a production run needs **all** of:

1. `Tenant.is_demo` true
2. slug exactly `nrbchem`
3. name exactly `Nairobi Chemists`
4. `--confirm-tenant-id` matching the exact UUID
5. a Platform Owner approval bound to the manifest digest
6. `--allow-production-demo-seed`
7. `--confirm-tenant-slug=nrbchem`
8. a dry-run manifest whose digest matches the approval
9. external notifications disabled
10. outbound FHIR writes disabled
11. no live provider credentials configured
12. a recorded database backup
13. capacity checks passing
14. existing data classified `EMPTY_SAFE_TO_SEED` or `DEMO_DATA_PRESENT`
15. requester ≠ approver
16. approval unexpired

`--allow-demo-seed` **never** permits a production run. It establishes
non-production intent and nothing more. Production requires its own flag, and
the flag alone is not sufficient either.

Every condition is checked independently and the battery fails closed: a missing
backup, an unreadable capacity figure or an unclassifiable record blocks the run
rather than being assumed benign.

---

## 5. Reset

Refused in Stage 1, deliberately. When implemented it will archive, not delete.

Eight model families declare themselves immutable — audit events, inventory
ledger entries, clinical overrides, pharmacist verifications, supplied
prescriptions, integration evidence, POS documents and PO revisions. A reset
that deleted them would violate the repository's own policy, so
`DemoScenarioObject.reset_eligible` is `False` for those domains and archival
supersedes them in place.

---

## 6. Pilot profile

`nairobi-chemists-pilot` exists to measure correctness and runtime, not to move
volume. 7,869 planned objects over 9 months:

| | |
|---|---|
| branches / warehouses | 2 / 1 |
| users | 16 |
| patients | 500 |
| stocked SKUs | 400 |
| batches | 750 |
| inventory ledger entries | 4,000 |
| sales / dispensing events | 1,500 |
| prescriptions | 375 |
| claims | 75 |
| suppliers / POs | 8 / 40 |
| transfers / recalls | 20 / 2 |
| shifts / notifications | 60 / 120 |

Scaling up waits on measured runtime, database growth, disk impact and report
performance from a completed pilot — not on estimates. The manifest carries
estimates and labels them unmeasured.

---

## 7. Troubleshooting

| Message | Cause |
|---|---|
| `is designated a demo tenant (is_demo=True)` | Run `designate_demo_tenant` first |
| `outbound FHIR write interactions are disabled` | Set `DAWATRACE_FHIR_WRITE_INTERACTIONS_ENABLED=0` locally |
| `--allow-production-demo-seed supplied` | Production needs its own flag; the generic one is not enough |
| `Stage 1 implements planning only` | Expected. Use `--dry-run` or `--validate-only` |
| `never creates a tenant` | The engine only ever seeds a tenant that already exists |
| `Reset is not implemented in Stage 1` | Expected |
