# ADR: Canonical DawaTrace Clinical Models

- Status: Accepted for Phase 2
- Date: 2026-07-22

## Context

FHIR-shaped resources and prescription-adjacent clinical rows existed in more
than one source location. Direct ORM persistence would not preserve cross-resource
invariants.

## Decision

`apps.clinical` owns Encounter, Condition, Observation, DiagnosticReport,
ClinicalDocument, and MedicationAdministrationRecord. Patient allergy and active
medication remain in `apps.patients`, where patient context is assembled. All
clinical writes use `ClinicalDomainService`; the compatibility import under
`apps.prescription.services.clinical_domain` delegates to that service.

## Preserved Invariants

- tenant-owned references and immutable patient ownership
- same-patient relationships across encounter, result, and report
- valid state transitions and clinical time ranges
- quantity/string observation value requirements
- document URL, SHA-256, content type, and size validation
- administration status, medicine, performer, and prescription consistency

## Deprecated or Omitted

Duplicate source model families and direct generic ORM write paths are omitted.
Clinical binary content is held by the independent document-storage context, not
inside clinical rows.

## Migration and Compatibility

Fresh migrations split the former combined prescription migration into dedicated
clinical migrations. The 19-resource FHIR registry targets these canonical rows.

## Risks

FHIR profile-specific validation beyond the Phase 2 baseline, consent policy, and
clinical retention schedules require later governance approval.
