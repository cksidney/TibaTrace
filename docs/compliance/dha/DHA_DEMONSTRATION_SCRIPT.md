# TibaTrace DHA demonstration script — planned, not performed

**Updated:** 26 October 2026<br>
**DHA status:** Owner-declared certified; certificate/scope not verified in the reviewed evidence<br>
**System DPIA:** NOT APPROVED<br>
**Demonstration target:** DHA-authorized sandbox and exact approved release/client builds, to be recorded before a session

This script is for planning only. It does not establish that DHA has scheduled or accepted a demonstration. Do not use the old rc5 script's named patient, UPI, unsupported endpoint names or production records. Use only approved synthetic fixtures in a segregated environment. Follow the [current DHA regulatory guide](https://certification.dha.go.ke/regulatory-guide) and instructions for the actual audit.

## Before the session

1. Confirm DHA's category, criteria, written agenda, environment, allowed data, test credentials and reviewers.
2. Record the exact server commit/image digest, database migration level, signed POS versions, OS/device models and tenant configuration.
3. Confirm synthetic fixtures, test-only provider endpoints, backups and rollback. Disable live national exchange, payment and messaging destinations unless DHA explicitly authorized a sandbox route.
4. Verify access roles, masking, audit capture and evidence storage. Do not show credentials, secrets, unrelated tenant records or real patient data.
5. List each demo step against the criterion ID in the [test plan](DHA_CERTIFICATION_TEST_PLAN.md); mark unimplemented or unverified behavior plainly.

## Walkthrough

1. **Identity and tenant context:** sign in as the least-privileged demonstration user. Show tenant/facility context and an authorized synthetic patient search; demonstrate a denied cross-tenant request using the approved test procedure.
2. **Prescription intake:** show direct prescription entry and any supported upload path with synthetic material. Show provenance, validation, and safe rejection of malformed/unsupported content. Do not describe an upload as clean unless an active scanner returned CLEAN.
3. **Clinical review:** show allergy/interaction screening, role restriction and documented pharmacist review/override using test fixtures.
4. **Dispensing and inventory:** demonstrate only valid state transitions, batch/expiry checks, quarantine behavior, final check, supply and audit history.
5. **Payment and receipt:** use a sandbox/simulator only. Demonstrate pending, failed, duplicate/idempotent and successful state behavior plus refund/void controls. No real card, M-PESA or tax transaction should be initiated in a demonstration unless specifically authorized.
6. **Interoperability:** if DHA has enabled a sandbox route, show its approved profile/version, authorization, request provenance, acknowledgment, failure/retry and audit trail. Otherwise state that the production integration is disabled and show its activation gate without transmitting data.
7. **Security and continuity:** demonstrate session expiry/revocation, role denial and the approved backup/restore evidence. State honestly whether MFA, scanning, recovery or any other control is still open.
8. **Close:** list criterion outcomes, unanswered questions, defects, artifact IDs, owners and follow-up dates. Obtain DHA's written result through its official process; do not present this internal walkthrough as certification.

## Evidence record

For each step preserve criterion, release/client identity, synthetic fixture reference, sanitized screenshot/log, expected/actual outcome, tester/witness/date, result and artifact hash/location. Store the evidence in the restricted compliance repository. Redact secrets and sensitive data.

**Demonstration result:** Not performed under this script.<br>
**Approval:** Product/clinical/security/privacy owners and DHA representative — pending.
