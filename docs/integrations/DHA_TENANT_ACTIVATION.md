# DHA tenant integration and activation

Implementation reviewed 25 October 2026. This is software integration support;
it does not establish DHA certification, an approved DPIA or production access.
Existing unapproved DPIA findings still need evidence and sign-off.

## HQ setup

Open **National Integrations → Tenant DHA connections** in the selected pharmacy.
Add a connection for each branch and environment. Enter the assigned HIE API base
URL, exact allowed hostname, verified Facility Registry code and credential
**reference names**. Credential values go into the protected server environment.
The sample [environment file](../../deploy/tibatrace/.env.dha.example) contains no
working credentials or encryption keys.

Map the local user ID to the requesting clinician's verified PUID. Map national
prescriber IDs to local practitioner UUIDs; map `coding-system|code` to governed
tenant SKU UUIDs. Unit mappings bind the local quantity unit to its national
`system` and `code`; no pack conversion is inferred. Mapping local IDs outside
the selected tenant is refused. Patient CR identifiers use the existing
patient-identity evidence/verification workflow; a local patient UUID is never
presented as a national identifier.

Only the Platform Owner can probe connectivity or activate a connection. A probe
obtains a real token and checks the configured facility; it is not a UAT pass.
Activation additionally requires evidence references for sandbox UAT, security,
the system DPIA and facility approval. Production adds DHA approval and production
access evidence. Missing credentials, encryption keys, current validation, an
operational tenant or an active branch block activation/traffic. Changing
configuration increments its revision, disables it and requires validation and
approval again. The existing platform DHA provider kill switch also blocks these
connections when suspended, revoked or decommissioned.

## Security and operations

- Connections are tenant/branch owned; all queries, credentials, consent and
  command keys use that context. Branch assignments and named DHA capabilities
  are checked on the server and rechecked when a worker sends a command.
- `TIBATRACE_DHA_DATA_KEYS` is an ordered JSON array of Fernet keys supplied by
  the secrets manager. Encrypts consent context, requests, responses and callback
  bodies. Prepend a new key for rotation; retain historical decryption keys until
  ciphertext is migrated. Back up keys securely and test recovery. Losing them
  makes journals unreadable; there is no plaintext fallback or application-secret
  derived default key.
- The token client uses the published form-encoded `/tenants/token` contract.
  Tokens stay in bounded process memory, expire early and are isolated by
  connection/revision/credential digest. They are not returned to the browser.
- HTTPS certificate verification is mandatory, redirects and environment proxies
  are disabled, and destinations must satisfy the server and connection host
  policies. Requests and responses are size/time bounded. Error messages do not
  expose remote bodies, tokens or credentials.
- `TIBATRACE_DHA_ENVIRONMENT_BASES` binds exact server-approved base URLs to
  sandbox/production. Production has no default URL; supplying a sandbox URL on a
  production connection does not activate it. Add the DHA-issued production base
  and its host to the protected server policies before validation.
- Audit records contain local references, operation names and outcomes. OTPs are
  removed from request snapshots after an attempt. Encryption does not replace
  the controller-approved retention schedule, access review or DPIA controls.

Celery Beat schedules `apps.integrations.tasks.process_dha_exchanges` once per
minute in the existing protected worker runtime. For a manual bounded run use
`python manage.py process_dha_exchanges --limit 50`. Scheduling does not activate
connections. It is a bounded job, not a long-running daemon. It processes pending/retry commands and recovers expired worker leases.
Read failures and explicit rate-limit refusals have bounded jittered backoff.
Interrupted or ambiguous mutations become `UNCERTAIN`, not automatic resubmissions.
Use a PostgreSQL deployment for concurrent worker locking.

## Endpoint surface

Tenant API base: `/api/nif/dha/`.

| Local route | Behaviour |
|---|---|
| `connections/` GET / POST | Tenant connection list and creation |
| `connections/{id}/` PATCH | Revise configuration and disable the old revision |
| `connections/{id}/probe/` POST | Owner-only token/facility validation |
| `connections/{id}/activate/` POST | Owner-only evidence-backed activation |
| `connections/{id}/suspend/` POST | Immediately gate further traffic |
| `connections/{id}/catalogue/` GET | Named upstream operations and capabilities |
| `connections/{id}/visits/` GET / POST | Create/list operator-owned patient consent contexts |
| `connections/{id}/commands/` POST | Governed, journalled operation execution |
| `connections/{id}/exchanges/` GET | Metadata-only exchange queue/history |
| `connections/{id}/confirm-bundle/` POST | Confirm each transmitted resource by read-back |
| `connections/{id}/resolve-uncertain/` POST | Owner records a provider-verified investigation outcome |
| `connections/{id}/callbacks/` GET | Authorised callback review; tokens remain redacted |
| `callbacks/{connection}/{entity}/` POST | Authenticated national status notification receiver |

Commands take `operation`, `payload`, `idempotency_key`, optional local `visit`
UUID and optional `path_values`. The catalogue fixes the HTTP method/path;
operators cannot submit arbitrary URLs, methods, headers or cross-patient search
expansions. A retry key cannot be reused for another actor or different command.

Implemented operation groups:

- Patient, facility and health-worker registry lookup; terminology search/mappings.
- SHR open visits, consent request/verify/status/resend, refresh and visit closure.
- Consented patient records, observations, facility-directed referrals and security
  label lookups.
- Medication supply Bundle preparation, asynchronous receipt and per-resource
  read-back confirmation.
- SHA eligibility, benefits/sub-benefits/interventions, contacts, OTP/biometric
  authorisation and claim visit, billing/diagnoses/attachments, previews, line
  correction/resubmission, coverage selection, tariffs, preauthorisation/cancellation,
  discharge and claim submission/closure.
- Callback endpoint/operation registration, authenticated receipt and review.
- Remittance reads through tenant-assigned contract routes, as described below.

## Consent and pharmacy workflow

1. Resolve and verify the patient's CR identifier and map the requesting PUID.
2. Create a local visit for that patient. Request consent using `visit_type: OP`
   (or IP where applicable). The server supplies the facility, patient, practitioner
   and requesting operator, ignoring browser attempts to replace that context.
3. Verify the OTP or record refusal. Emergency/incapacity paths require separate
   `dha.emergency` authority and a reason. Representative consent carries the
   representative CR ID and relationship. No clinical access follows a refusal.
4. Read only the required record types. The per-visit consent token is encrypted
   and applied server-side. Its local cache lifetime is five minutes; refresh an
   expired token against an open visit. A closed/rejected visit cannot be reopened
   by replaying its old consent status.
5. POS DHA intake uses `local-visit-uuid:MedicationRequest-id`. It reads the order
   through consent, resolves medication references/codings, validates local
   prescriber/SKU/unit mappings and reconciles completed national dispensing
   history, including pagination. The existing POS intake then creates an
   **unverified** prescription for legal, clinical and pharmacist review.
   The national order ID remains its stable intake identity across consent visits,
   preventing the same order from being received twice under different visit IDs.
   Repeat/refill orders without an authoritative remaining-repeat contract are
   explicitly refused, rather than assuming a fresh entitlement.
6. After actual supply, submit `bundle_submit` with `supply_id` and reviewed
   `security_labels`. The server builds FHIR from the governed medicine supply,
   with tenant, patient, branch, quantity, prescription and visit linkage. Draft
   sales and arbitrary caller-authored clinical Bundles are refused. Imported
   national orders are referenced without replacing their original prescribing
   content. Missing dates, mappings or labels require review.
7. Acknowledgement is `ACCEPTED`, not proof of storage. `confirm-bundle` checks
   every submitted resource ID/content and marks `CONFIRMED` only after read-back.
   It may use a fresh consented visit for the same patient if the original visit
   has ended. Close the national visit when care ends; an OTP-gated closure stays
   `CLOSING` until verification returns its end date.

## Claims, attachments, callbacks and remittances

SHA authorisation tokens and SHR consent tokens are separate values. Claims use
the SHA token stored for the patient's local visit; caller-supplied consent tokens
are discarded. Submission/closure prevents ordinary further billing edits.
Provider adjudication, actual remittance and POS payment remain separate states.
Receiving a callback never pays or clinically approves a local transaction.

Claim attachments and multipart preauthorisations use stored clinical document IDs,
not disk paths or arbitrary remote URLs. The document must belong to the visit's
patient/tenant. A required malware scan must be clean. The previously authorised
server policy deferring scanning is respected: only explicit `NOT_SCANNED`
documents may additionally pass while that policy is disabled, with a separate
export audit event. They remain labelled not scanned; infected, pending and
scan-error documents never pass. Re-enabling the policy requires clean scans.

Arrange the callback bearer secret with DHA, set the local secret reference, and
provide DHA's corresponding `callback_hie_secret_ref` plus `hie_tenant_id`.
Register a separate endpoint/operation for `claim`, `preauth` and `authorization`.
The server generates the destination from its approved public callback base;
registration cannot redirect notifications to an operator-provided host. Receiver
authentication, facility/entity/tenant checks and digest deduplication precede
encrypted retention. Stale/out-of-order notifications remain reviewable instead
of overwriting local financial state.

The current public DHA remittance guide describes the workflow and `bank_reference`
but its current generated API catalogue does not publish the matching routes.
There is deliberately no guessed route. Once DHA confirms them, configure
`remittance_paths.remittances` and `remittance_paths.remittance_claims` as plain
relative GET paths. The service injects the approved branch facility context and
refuses these operations while unbound. Revalidate the changed configuration.

## Validation before production activation

Use the assigned DHA sandbox records and current contract/profile versions. Prove
identity matching, refusal/expiry/representative consent, record read/write/read-back,
partial supply, cancellation/correction, claim rejects and preauthorisation,
document requirements, duplicate/out-of-order callbacks, timeouts, worker restart,
tenant/branch separation, key recovery and provider outages. Obtain DHA/facility
approval and production credentials separately. Automated local tests exercise
the implementation with controlled provider responses; they are not national UAT.

Official references checked during implementation:

- [DHA API catalogue](https://hie-docs.dha.go.ke/catalog)
- [SHR lifecycle](https://hie-docs.dha.go.ke/docs/sharedHealthRecord/gettingStarted/intro)
- [SHR records contract](https://hie-docs.dha.go.ke/sharedhealthrecord/shr-records)
- [Facility scope](https://hie-docs.dha.go.ke/docs/authentication/process/facility-identification)
- [Callbacks](https://hie-docs.dha.go.ke/docs/claims/guides/status-callbacks)
- [Remittances](https://hie-docs.dha.go.ke/docs/claims/process/remittances/remittanceProcessOverview)
- [ePrescription guide, currently draft 0.1.0](https://fhir.dha.go.ke/ig/erx)
- [DHA certification](https://certification.dha.go.ke/)
