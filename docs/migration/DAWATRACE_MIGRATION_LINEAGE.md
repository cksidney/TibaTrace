# DawaTrace Migration Lineage

## Strategy

DawaTrace has a zero-based migration graph. It does not copy the Mercato graph or
depend on Restaurant, Retail, Factory, inventory, sales, finance, or user tables.
Source migrations are lineage references only.

| Mercato source lineage | DawaTrace migration | Treatment |
| --- | --- | --- |
| `prescription.0001_initial` | tenancy, organizations, patients, practitioners, medicines, prescription `0001` | transformed and split into canonical contexts |
| `prescription.0002_*provider*` | `prescription.0001_initial` | provider config/outbox retained with tenant keys; unrelated source fields omitted |
| `prescription.0003_*knowledge*` | `cds.0001` through `0004` | transformed into source-attributed provider CDS schema |
| `prescription.0004_*knowledgepack*` | no direct table copy | marketplace/package schema omitted; licence/source fields retained in releases |
| `prescription.0005_*clinicalevent*` | workflows/notifications `0001`; clinical `0001`-`0003` | durable event and canonical clinical concerns split |
| `prescription.0006_*terminology*` | terminology `0001`; clinical `0001`-`0003`; documents `0001`-`0002` | transformed and split |
| `prescription.0007_phase_7_1_tenant_ownership` | every context's initial migration | tenant columns/constraints start enforced at zero |
| `prescription.0008_phase_7_2_2_explicit_tenant_scope` | CDS/terminology/FHIR initial migrations | explicit tenant/global checks start enforced at zero |
| `fhir.0001_fhir_idempotency_record` | FHIR `0001`-`0002` | transformed to independent identity and idempotency rows |
| Mercato authn/organization/user schemas | identity/tenancy/organizations `0001` | contract reimplementation; no source user FK |
| no source equivalent | crosswalks `0001` | new immutable migration/reconciliation boundary |

Machine-readable mapping: `artifacts/evidence/migrations/migration_lineage.json`.

## Validation

- Fresh SQLite evidence database migrated from zero: pass, 57 DawaTrace tables.
- Drift detection: no model changes pending.
- Prescription `0002` rollback/reapply: pass.
- CDS `0004` rollback/reapply: pass.
- FHIR `0002` rollback/reapply: pass.
- Crosswalk `0001` zero/reapply: pass.
- Documents `0001`/`0002` zero/reapply: pass.
- Final migration plan: no operations.
- Schema introspection: `artifacts/evidence/migrations/schema_inspection.json`.

PostgreSQL is the production target. SQLite migration evidence validates graph
independence; CI repeats zero migration on PostgreSQL 18.
