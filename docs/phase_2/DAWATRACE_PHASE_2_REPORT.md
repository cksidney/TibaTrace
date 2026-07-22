# DawaTrace Phase 2 Report

## Executive Summary

Phase 2 created an independently runnable DawaTrace modular monolith with its own
configuration, database graph, tenant/identity layer, clinical core,
prescription state machine, CDS, terminology, FHIR R4 gateway, tests, CI, Docker
build, evidence, and documentation. It has no runtime import, foreign key,
filesystem link, queue, or database dependency on Mercato-OS.

**Decision: `DAWATRACE_CORE_EXTRACTED_WITH_BLOCKERS`**

The core boots, migrates from zero, passes all 166 tests, builds, and passes local
security controls. Non-critical external/provenance gates prevent an unqualified
extraction or production-readiness claim.

## Source Baseline

- Mercato commit: `5c84ad1781d843654b4bc446466384fee18394f1`
- Branch: `main`
- Source status: dirty, with 112 modified/staged and 1,212 untracked paths
- Selected files: 225
- Manifest SHA-256:
  `6bf858c24d4e2248e66f44e3e9eabe9b1a3fe723b8b5b9b9aa7114f1d7352f46`
- Source release tag: not created

Every selected working-tree file is independently hashed. The source commit is
not represented as sufficient provenance.

## Extracted Contexts

Tenancy, identity, organizations, medicines, patients, practitioners,
prescription/dispensing foundation, clinical resources, CDS, terminology, audit,
workflows, notifications, crosswalks, documents, and FHIR are present. The
administrative shell verifies login, tenant inference, resource visibility, CDS
and terminology visibility, FHIR health, and system health.

Restaurant, Factory, Retail, Forecourt, OMS, loyalty, finance, procurement,
warehouse, complete inventory, payments, Windows POS, Android POS, and full HQ UI
were not copied.

## Canonical and Domain Decisions

Canonical Patient, Practitioner, Prescription, and Clinical model families are
owned by DawaTrace and documented in ADRs. `ClinicalDomainService` is a real
invariant boundary: it validates same-tenant/same-patient references, immutable
patient ownership, temporal rules, required values, state transitions, document
hashes, and secure URLs before persistence. FHIR writes call domain services.

The prescription workflow enforces:

```text
DRAFT -> CLINICAL_REVIEW -> BLOCKED|APPROVED -> DISPENSING
      -> READY_FOR_PAYMENT -> PAID -> DISPENSED -> REVERSED
```

No transition from selection to payment bypasses clinical review.

## CDS and Terminology

CDS distinguishes `PASS`, `WARNING`, `BLOCK`, `KNOWLEDGE_UNAVAILABLE`, and
`ERROR`. Missing or failed knowledge never becomes `PASS`. Knowledge is
provider-based, source-attributed, versioned, tenant-first with explicit global
fallback, and override-capability controlled. Only test/demonstration content is
included.

Terminology supports versioned CodeSystem and ValueSet registrations,
`$validate-code`, `$expand`, imports, exclusions, display/inactive validation,
paging, and tenant isolation. Unsupported compose filters fail explicitly.

## FHIR Baseline

The runtime is HL7 FHIR R4 4.0.1 with `fhir.resources==6.5.0` and
`pydantic==1.10.26`. The registry contains 19 resource types. Tests cover every
resource's R4 parse/render, tenant-scoped read/search, qualified references,
transaction/batch Bundles, idempotency, and OperationOutcome errors. Historical
Mercato canonical URIs are preserved as interoperability lineage only.

Fresh external HAPI and Firely suites were not run. No Firely, `FHIR_PORTABLE`,
or production-certification claim is made.

## Migrations and Crosswalks

The independent graph migrates 57 DawaTrace tables from zero without Retail,
Restaurant, Factory, or other Mercato migration dependencies. Drift detection and
the final migration plan are clean. Prescription, CDS, FHIR, crosswalk, and
document migrations were rolled back and reapplied successfully.

Immutable tenant-scoped crosswalks preserve source system/entity/identifier,
target UUID, source hash, batch, and metadata without a live Mercato foreign key.
Tests cover duplicate prevention, immutability, isolation, idempotent resolution,
and missing targets.

## Exact Test Results

| Suite | Passed |
| --- | ---: |
| Platform, tenancy, identity, RBAC/ABAC, audit | 13 |
| Clinical resources and domain invariants | 17 |
| Prescription, dispensing, CDS | 16 |
| FHIR R4 gateway | 66 |
| Terminology | 22 |
| Infrastructure, crosswalk, jobs, documents, security, admin shell | 32 |
| **Total** | **166** |

No tests were skipped or xfailed. Shared TypeScript typecheck and build passed.

## Security and Build

`pip check`, Ruff, Django test and production-template checks, Bandit, local
secret scan, UUID audit, tenant-manager audit, tenant-ownership audit, OpenAPI
validation, SBOM generation, and Docker build passed. Bandit found 0 issues over
10,708 lines; the manager audit reviewed 54 models with 0 unreviewed findings and
one documented identity manager exception.

The image is multi-stage, base-digest pinned, non-root UID/GID 10001, labeled, and
health checked. Exact final image metadata is tracked separately under
`artifacts/evidence/build/` after repository initialization.

## Intentional Divergence

The dead, unwired legacy prescription plugin subtree was omitted because it
depended on absent knowledge models and duplicated the canonical `apps.cds`
implementation. This is an explicit consolidation, not a silent omission.
Provider adapters remain fail-closed, notification delivery remains an outbox
without external transport, and object storage uses the secured local adapter
with external/malware hooks reserved for later phases.

## Blockers and Required Approvals

1. The Mercato source baseline is dirty/unreviewed and needs a reviewed commit/tag.
2. Online Python/npm vulnerability intelligence and container CVE scanning must
   run in an approved environment; private dependency metadata was not exported.
3. Fresh protected HAPI R4 and licensed Firely certification remain pending.
4. PostgreSQL-scale migration/concurrency, backup/restore, production IAM, key
   management, Redis TLS/ACL, object-store IAM, malware scanning, and penetration
   testing remain pending.
5. Licensed clinical knowledge, clinical governance, regulatory approval, and
   production migration reconciliation are not Phase 2 deliverables.

Approval is still required for the canonical model migration contract, identity
federation design, clinical knowledge provider/licensing, retained historical
FHIR canonical URIs, production infrastructure, and Phase 3 scope.

## Production Controls

No VPS or production deployment occurred. No production data was read or changed.
The Mercato Pharmacy implementation was not removed. DawaTrace was not connected
to a Mercato database, and no release tag was created.

## Phase 3 Recommendation

First close source provenance and security/FHIR certification gates. Then build a
rehearsed, reconciled data-migration pipeline using immutable crosswalks; add the
licensed clinical knowledge provider and secured production adapters; extract
medicine inventory, batch/expiry/FEFO, controlled-drug workflows, and pharmacy
POS clients behind the validated prescription/clinical contract; finally run
staged tenant migration, rollback, performance, and operator acceptance gates.
