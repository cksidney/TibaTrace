# Pharmacist Verification

## Preconditions

Verification requires:

- passed legal validation;
- a completed current pharmacist review;
- a current DUR evaluation that is neither unavailable nor erroneous;
- no unresolved critical findings or high/critical intake findings;
- no open interventions;
- valid prescriber authority;
- active patient and in-date prescription;
- configured controlled-medicine evidence and authority where applicable.

## Accountability

The actor requires `prescriptions.pharmacist_verify`; controlled verification additionally requires `prescriptions.controlled_verify`. The record captures the context hash, checks, decision, actor, justification, time, and persistent idempotency key.

Verification rows are immutable and cannot be deleted. Revocation is represented by revocation metadata on the original row and a domain event. Any material instruction change revokes the active decision and returns the prescription to clinical review.
