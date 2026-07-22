# DawaTrace Bounded Contexts

| Context | Ownership | Primary enforcement |
| --- | --- | --- |
| Tenancy | Tenant identity and lifecycle | explicit tenant IDs and fail-closed managers |
| Identity | Users, roles, ABAC denies, external identities, service accounts | tenant-qualified capabilities |
| Organizations | Healthcare organizations, locations, identifiers | same-tenant organization/location links |
| Patients | Patient demographics, identifiers, allergies, active medication | canonical patient UUID and tenant ownership |
| Practitioners | Professionals, identifiers, licences, roles | tenant and organization/location consistency |
| Medicines | Minimal canonical medicine reference | tenant or explicitly global scope |
| Prescription | Prescription aggregate, transitions, verification, dispense/fill | workflow and dispensing services |
| Clinical | Encounter, condition, observation, report, document reference, administration | `ClinicalDomainService` invariants |
| CDS | Knowledge releases/rules, evaluations, findings, overrides | source attribution and fail-closed outcomes |
| Terminology | Versioned CodeSystem and ValueSet registrations | tenant-first/global fallback and RBAC |
| FHIR | R4 registry, converters, references, bundles, identities, idempotency | authenticated tenant-qualified boundary |
| Documents | Clinical binaries and access events | signed actor/tenant tokens and SHA-256 |
| Audit | Immutable security/domain audit records | append-only application behavior |
| Workflows | Domain events and tenant-explicit jobs | scoped lookup and denied-job audit |
| Notifications | Tenant outbox only | no Phase 2 external transport |
| Crosswalks | Immutable legacy-to-DawaTrace identifiers | no live source-system foreign keys |

Contexts communicate through UUID references, domain services, or durable events.
They do not access Mercato databases or filesystem paths at runtime.
