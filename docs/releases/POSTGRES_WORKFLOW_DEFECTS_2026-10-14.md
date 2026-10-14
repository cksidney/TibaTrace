# PostgreSQL workflow defects — release held

## Evidence

Real PostgreSQL 18.6 run [38500572420](https://github.com/cksidney/TibaTrace/actions/runs/38500572420)
checked out exact rc40 source `80946fda4ffc4e8b565967d60e0f895ba9235c0e`:
2,117 collected tests, 35 failures, four setup errors, no skips. This is not a
passing release. The source/database JSON and JUnit artifact are retained.

The corresponding SQLite suite did not expose these PostgreSQL execution
failures. Mandatory real-PostgreSQL publication gates are retained. rc41/42
candidates were stopped and no candidate image was activated. Production rc37
health is green, but these unchanged business paths require the targeted repair;
health checks alone must not be presented as successful workflow acceptance.

## Targeted repair under validation

- Guest retail scan/quantity queries keep transaction, branch and store locks
  while excluding the nullable customer outer join from the lock targets.
- Refund execution keeps tenant/sale/request locking while excluding nullable
  return-location and reviewer joins. Independent approval, current till funding,
  retry safety and quarantine custody controls remain in force.
- Stocktake revision keeps session/count/SKU/location locking while excluding
  the nullable batch join. New coverage recounts an unbatched zero observation.
- Opening setup keeps source/tenant locking without targeting the nullable
  reviewer join. Manager confirmations, quarantine and independent release are
  unchanged; no live source rows are seeded or released by the test run.
- B2B reservation materialises eligible balance rows in deterministic lock order,
  then groups that protected snapshot by location. This removes unsupported
  `MIN(uuid)` and `FOR UPDATE`/`GROUP BY` execution without removing the stock
  locks. New coverage spans multiple locations and batches in FEFO order.
- Inventory-velocity tests assert exact numeric units rather than SQLite-specific
  decimal string padding, with fractional-unit coverage and unchanged source
  export precision. No failed assertion is skipped or converted into a pass.

The separate unscoped-reviewer audit failure was fixed in rc41 and the scanner
was not weakened. Full new-source gates, image provenance, backup and actual
post-activation checks are still required. Initial isolated local PostgreSQL
verification passed all 97 affected tests. The final expanded affected-workflow
suite passed all 99 tests on both local PostgreSQL 18.1/UTF-8 and SQLite, with
no failures, errors or skips. All 69 commercial/report/admin/lookup checks also
passed on the same PostgreSQL database. The clean-checkout full suites are still
pending; these focused results do not certify the whole system.
