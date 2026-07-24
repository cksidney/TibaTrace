# Prescription Lifecycle

## Independent State Dimensions

The prescription keeps separate legal-validation, clinical-review, pharmacist-verification, and dispensing states. The business status summarizes the current stage but is not the sole safety decision.

```text
RECEIVED
→ INTAKE_REVIEW
→ LEGALLY_VALIDATED
→ CLINICAL_REVIEW
→ PHARMACIST_VERIFIED
→ READY_FOR_DISPENSING
→ PARTIALLY_SUPPLIED / SUPPLIED
→ CLOSED
```

Alternate states include `ON_HOLD`, `INTERVENTION_REQUIRED`, `REJECTED`, `CANCELLED`, `EXPIRED`, and `RETURNED`.

## Write Boundaries

- `PrescriptionIntakeService` creates the instruction and immutable item snapshots.
- `PrescriptionValidationService` records every legal/intake finding.
- `PharmacistReviewService` owns clinical review.
- `PharmacistVerificationService` owns accountable authorization and revocation.
- `PrescriptionLifecycleService` owns hold, release, and cancellation.

Material patient, prescriber, date, validity, controlled-status, repeat, medicine, dose, route, frequency, duration, or quantity changes revoke active pharmacist verification. Supplied instructions cannot be edited; a corrected prescription is required.

## Work Queues and Notifications

Each transition opens the next tenant- and branch-scoped `ClinicalWorkItem` and closes completed work automatically. The read-only `/api/clinical/work-items/` endpoint filters work by the caller's effective capabilities and optional branch, queue type, and status. Patient notifications use the existing outbox and contain references and requested actions only, not medicine or sensitive identity details.

Prescription intake creates a protected intake record in the existing document subsystem. Legal failure, approaching expiry, clarification, controlled review, verification, and downstream dispensing transitions create idempotent notification records where applicable.
