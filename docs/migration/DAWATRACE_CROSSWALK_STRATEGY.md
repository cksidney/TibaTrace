# DawaTrace Crosswalk Strategy

`LegacySystem` describes a source without storing credentials. A
`LegacyIdentifierCrosswalk` records tenant, source system, source entity/type ID,
target type/UUID, optional source hash, batch, migration time, and immutable
metadata.

## Guarantees

- unique source identity within tenant
- indexed target and migration-batch reconciliation
- immutable after creation and not application-deletable
- no foreign key, network call, or database link to Mercato
- unresolved rows may carry a null `target_uuid` and reconciliation metadata
- repeated resolution returns the same row
- another tenant cannot resolve the mapping

## Migration Use

1. Register a reviewed source environment without credentials.
2. Hash source payloads where lawful and appropriate.
3. Create crosswalk and target in one controlled migration unit.
4. On retry, resolve the crosswalk before creating a target.
5. Record unresolved targets explicitly for reconciliation.
6. Compare source counts/hashes and sign off before cutover.

Phase 2 creates the mechanism and tests only. It imports no production data.
