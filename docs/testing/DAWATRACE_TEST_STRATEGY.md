# DawaTrace Test Strategy

## Principles

Tests use isolated settings, SQLite in memory unless migration evidence requires a
file, local-memory cache, eager Celery, local email, and no live service calls.
External provider adapters are unconfigured and fail closed. Production datasets,
credentials, and Mercato databases are never used.

## Current Focused Suite

| File | Cases | Coverage focus |
| --- | ---: | --- |
| `test_platform_identity_security.py` | 13 | tenancy, identity, RBAC, ABAC, JWT, API scope, immutable audit |
| `test_clinical_domain.py` | 17 | canonical resources and `ClinicalDomainService` invariants |
| `test_prescription_cds.py` | 16 | 9 CDS/knowledge checks and 7 prescription/dispense checks |
| `test_fhir_r4_gateway.py` | 66 | runtime, 19 resources, conversion, read/search scope, bundles, references, outcomes |
| `test_terminology.py` | 22 | CodeSystem, ValueSet, operations, version/display/inactive, imports/exclusions/paging/RBAC |
| `test_infrastructure_security.py` | 32 | crosswalks, identity mappings, jobs/providers, documents, scans, health/admin shell |
| **Total** | **166** | independent Phase 2 core |

## Additional Gates

Ruff, Django checks, migration drift, empty migration, rollback/reapply, OpenAPI
validation, unsafe UUID scan, manager audit, Bandit, local secret scan, CycloneDX
SBOM, TypeScript typecheck/build, Docker build, non-root check, and in-container
Django check are release evidence.

## Explicit Exclusions

- full inventory, procurement, finance, payment, controlled-drug, and POS tests:
  those contexts are not extracted in Phase 2
- production data migration tests: no production data movement is authorized
- licensed clinical content efficacy: no licensed production dataset is included
- Firely certification: licensed/available infrastructure is not configured
- fresh external HAPI round trip: historical source evidence is retained, while
  this phase certifies local R4 semantics and does not claim `FHIR_PORTABLE`
- live malware engine and external object store: only the fail-closed adapter and
  local integrity boundary are in scope

Machine-readable manifest: `artifacts/evidence/tests/test_manifest.json`.
