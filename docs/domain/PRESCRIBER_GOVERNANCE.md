# Prescriber Governance

## Authoritative Record

`Practitioner` stores professional name, registration, profession, licensing body, licence dates and status, prescribing scope, controlled-medicine authority, organization, verification state, and audit actors.

## Verification

`PrescriberGovernanceService` is the write boundary. Verification requires `prescribers.verify` (with the legacy `practitioners.write` alias) and rejects missing registration, inactive records, invalid or expired licences, and future licence issue dates.

Prescription legal validation evaluates the prescriber's state on the prescription date. Configured prescribing scope and controlled-medicine authority are checked without encoding deployment-jurisdiction legal claims.

## Failure Behaviour

Invalid authority creates preserved prescription-validation findings. High and critical findings keep legal validation in `FAILED`, so clinical review and pharmacist verification cannot proceed.
