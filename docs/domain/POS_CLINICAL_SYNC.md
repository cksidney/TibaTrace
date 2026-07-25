# POS Clinical Data Synchronization

The clinical synchronization engine synchronizes offline screening actions, decisions, and overrides back to the central backend.

## Synchronized Entities

The sync protocol transmits the following clinical payloads:
- **Offline Screening Results**: Cached local evaluations and findings.
- **Pharmacist Decisions**: Recorded review outcomes and electronic signatures.
- **Clinical Overrides**: Reason codes, severe alert bypasses, and justification texts.
- **Counselling Records**: Patient counselling acknowledgements and refusal logs.

## Protocol Mechanics

- **Idempotency**: All sync items carry unique client UUIDs and transaction hashes to prevent duplicate processing.
- **Ordering & Retries**: Sequential queue processing with exponential backoff retries for failed transmissions.
- **Conflict Detection**: Version checks compare offline decisions against central prescription state.
- **Clinical Exception Workflow**: If an offline decision violates post-sync central rules, an automated `ClinicalExceptionTask` is created for clinical audit review.
