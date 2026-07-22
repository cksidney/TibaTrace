# ADR: Canonical DawaTrace Prescription

- Status: Accepted for Phase 2
- Date: 2026-07-22

## Context

Source code contained legacy prescription status, POS sale progression, provider
verification, and clinical-review state. Directly reusing a retail sale model
would allow clinical state to be bypassed.

## Decision

`apps.prescription.Prescription` and `PrescriptionItem` are canonical. Dispensing
uses `PrescriptionDispense` and `PrescriptionFill`. The enforced workflow is:

`DRAFT -> CLINICAL_REVIEW -> BLOCKED|APPROVED -> DISPENSING -> READY_FOR_PAYMENT -> PAID -> DISPENSED -> REVERSED`

All transitions run through `PrescriptionWorkflowService`. Dispensing runs through
`DispensingEngine`, requires `PAID`, an authorized user, an in-tenant location,
valid quantities, and a tenant-qualified idempotency key.

## Preserved Fields

Patient, prescriber, organization, location, number, issue/expiry, substitution
policy, clinical context hash/review, approval identity/time, payment reference,
medicine, dosage, frequency, duration, quantity, refills, route, and controlled
marker are preserved.

## Deprecated or Omitted

Retail cart, tender, tax, stock batch, accounting, and till foreign keys are not
part of the Phase 2 prescription aggregate. Provider plugin marketplace models
that referenced missing legacy knowledge classes were intentionally omitted;
the canonical provider-based CDS engine is `apps.cds`.

## Migration and Compatibility

The schema starts from zero and does not reuse Mercato migration history. Legacy
prescription IDs are crosswalked. Historical FHIR identifier systems remain on
MedicationRequest/MedicationDispense to preserve interoperability lineage.

## Risks

Inventory reservation, controlled-drug registers, payment orchestration, and POS
offline synchronization remain Phase 3 scope.
