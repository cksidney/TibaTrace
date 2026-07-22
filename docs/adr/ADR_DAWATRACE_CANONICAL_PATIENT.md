# ADR: Canonical DawaTrace Patient

- Status: Accepted for Phase 2
- Date: 2026-07-22

## Context

Phase 1 identified patient representations in Pharmacy workflows, prescription
models, and FHIR-facing code. Retaining more than one authoritative patient row
would make consent, clinical ownership, and FHIR identity ambiguous.

## Decision

`apps.patients.Patient` is the canonical patient. `PatientIdentifier`,
`PatientAllergy`, and `PatientMedication` are owned by the same bounded context.
Every row has an explicit tenant; the default manager fails closed without tenant
context. DawaTrace patient UUIDs are independent of Mercato identifiers.

## Preserved Fields

Internal reference, verification status, active state, legal/display names, date
of birth, sex, contacts, address, deceased marker, and structured metadata are
preserved. External identifiers move to tenant-owned `PatientIdentifier` rows.

## Deprecated or Omitted

Retail customer accounts, loyalty, receivables, till activity, and sales customer
foreign keys are not patient fields. They are omitted from Phase 2.

## Migration and Compatibility

Legacy IDs map through immutable `LegacyIdentifierCrosswalk` rows. FHIR reads and
writes resolve the canonical patient only. Patient ownership cannot be changed by
API update. Production data migration remains a later controlled workstream.

## Risks

Patient/customer matching policy, consent migration, duplicate reconciliation,
and master-patient-index rules require approval before production migration.
