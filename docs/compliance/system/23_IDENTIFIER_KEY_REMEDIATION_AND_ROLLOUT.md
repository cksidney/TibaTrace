# Patient identifier key remediation and rollout

**Prepared:** 26 October 2026, Africa/Nairobi<br>
**Scope:** DPIA-08 identifier lifecycle and related FHIR storage/lookup paths<br>
**State:** Implemented and locally validated; not deployed or independently assessed<br>
**Production evidence boundary:** rc71, `2965194a29311314e8a5772adfeee5af8c14a8f2`, as recorded in the [25 October review](21_DPIA_CURRENT_REVIEW_2026-10-25.md). That dated evidence packet has not been replaced by these source changes.<br>
**DPIA decision:** NOT APPROVED; this remediation addresses part of one finding.

## Implemented safeguards

Patient identifiers use two independently provisioned, versioned random keyrings:
one for Fernet authenticated encryption, another for HMAC-SHA256 lookup. HKDF-SHA256
separates tenants and cryptographic purposes. New encryption and lookup do not
derive keys from Django `SECRET_KEY`. Ciphertext carries its encryption version;
an additive database field records the lookup version. Production settings reject
missing, malformed or reused encryption/lookup material. These are application
keyrings; no KMS, HSM or independently verified host encryption is claimed.

Normal identifier model writes, including direct prescription/FHIR intake, encrypt
the value and clear its plaintext field. External identifiers retain their case
and internal spaces. National identity types retain their established normalized
lookup semantics. Hospital, insurance and OTHER identifiers include the system
namespace and preserve case in lookup; identical values in different hospitals
remain separate. System-qualified lookup cannot fall back to an unrelated local
patient reference. Ambiguous identifier references fail for governed resolution.

Authorized FHIR/DHA conversion reads verified protected values. A tenant mismatch,
unavailable historical key, tampered ciphertext, inconsistent digest or masked
suffix prevents use. FHIR reference audit events retain an opaque tenant-qualified
correlation digest instead of the supplied identifier. The existing actor,
capability, purpose and tenant checks still govern access; a cryptographic helper
is not an authorization decision.

The rotation command verifies the entire tenant before updates, detects duplicate
logical identifiers and corrupt cross-tenant relationships, and uses a single
database transaction. Normal writers and rotation share a tenant lock. Failure,
including an audit-write failure, rolls back every update. Output and rotation
audit metadata contain counts and key versions, never identifier values or keys.
Already-current rows are left unchanged on repeat execution.

Historical `SECRET_KEY` values are accepted only in the explicit legacy read and
migration list. They are never implicitly taken from the current application
secret and never used for new protection. A historic implementation may already
have uppercased an identifier; rotation cannot reconstruct discarded case. Confirm
such external mappings against their authoritative source before activating an
exchange.

Raw SQL, queryset `update` and `bulk_create` bypass model protection. Keep these
operations restricted to governed migrations/administration; the collector flags
plaintext, missing ciphertext and unknown key versions. Database roles and
operational review remain necessary. No universal database encryption constraint
is claimed by this source change.

## Configuration and custody

Configure the following in protected runtime secret storage for every backend,
worker, scheduler and administrative command. The example values in
[the deployment environment template](../../../deploy/tibatrace/.env.production.example)
are placeholders and must never be copied as live keys.

| Setting | Required value |
|---|---|
| `DAWATRACE_PATIENT_IDENTIFIER_KEYS` | JSON object mapping safe version IDs to separately generated, base64url-encoded random 32-byte encryption keys |
| `DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID` | An ID present in that encryption ring |
| `DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS` | JSON object of independently generated random 32-byte lookup keys, with distinct material for every version |
| `DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID` | An ID present in that lookup ring |
| `DAWATRACE_PATIENT_IDENTIFIER_LEGACY_SECRET_KEYS` | Explicit JSON list of all historical application secrets needed for legacy records/backups; `[]` only when none are needed |

Generate each key using a cryptographically secure random source, such as Python
`secrets.token_bytes(32)` followed by `base64.urlsafe_b64encode`. Write directly to
protected secret storage; do not print keys to chat, CI logs or ordinary shell
history. Keep key custody separate from the database and object/backup archives,
with named owners, restrictive access, protected recovery copies and access audit.
The source does not provision a live secret manager or resolve the current
same-host backup/key custody finding.

Retain all encryption and lookup versions for live records and retained backups.
Changing the active ID only changes new writes. Searches check all retained lookup
versions; missing historical lookup versions block unsafe lookup/writes. Retain
legacy secrets until both live migration and every retained legacy backup's
recovery/expiry requirements have been verified. Retired-key deletion is a
separate governed action, never an automatic side effect of rotation.

## Controlled rollout

This is a procedure to execute after the release and operational prerequisites,
not evidence that deployment or a production rotation has occurred.

1. Complete full release CI, including PostgreSQL 16 matching production,
   vulnerability scans and immutable image provenance. Confirm tenant inventory,
   historical keys and backup restoration access. Local PostgreSQL 18 validation
   does not substitute for the production-major release gate.
2. Arrange a maintenance interval and quiesce every identity writer, including
   API, workers, scheduled jobs, imports and integration receivers. Take a
   coordinated protected DB/object/configuration snapshot and record the rollback
   point. Size the restore environment separately from the constrained live VPS.
3. Provision all independent and historical keys in protected runtime storage;
   verify every service/administrative process receives the same keyring versions.
   Keep DHA, EMR and payment activation states unchanged.
4. Apply `patients.0003_patientidentifier_lookup_key_id` using the new immutable
   backend image while old writers remain stopped. Do not mix old and new writers:
   old code cannot read new ciphertext, and the added column changes insert
   requirements. The schema migration does not decrypt or rotate existing rows.
5. For each explicitly identified tenant, run the commands below through the
   trusted backend runtime. The default is a no-data-change preflight. An unknown
   historical key, duplicate, corruption or tenant inconsistency stops conversion;
   restore keys or resolve the governed identity issue before retrying.
6. Verify no plaintext, missing ciphertext or unknown key versions remain; check
   authorized reveal, exact system/case lookup, masked unauthorized responses,
   direct prescription/FHIR intake and tenant isolation with synthetic data.
   Retain counts, audit events, source identity and the operator's dated result in
   restricted evidence storage.
7. Start API/workers and exactly one scheduler on the same new digest; verify
   health, queues and canary transactions before reopening writes. Preserve the
   paired rollback snapshot and historical keys. Once new writes are accepted,
   rollback needs a reviewed delta/reconciliation plan, not a blind old restore.
8. Exercise DB-plus-key recovery in an isolated environment with provider egress
   disabled; verify encrypted readback, lookup and key-version handling. Obtain
   independent review and update DPIA-08 only for controls actually evidenced.

```sh
# Replace the placeholder with an explicitly verified tenant UUID.
python manage.py rotate_patient_identifier_keys --tenant-id <tenant-uuid>
python manage.py rotate_patient_identifier_keys --tenant-id <tenant-uuid> --apply
python manage.py rotate_patient_identifier_keys --tenant-id <tenant-uuid>
```

Do not roll back only the application binary after new ciphertext or lookup
digests have been written. The old application cannot interpret the new scheme.
A pre-reopen rollback must restore the coordinated pre-change data/configuration
and compatible schema/image while writers remain quiesced. Never remove keys to
make a validation check pass.

## Validation and remaining closure

Local checks cover independent key configuration/startup, tenant and ciphertext
tamper denial, retained-version reads, mixed-version duplicate detection,
case/namespace preservation, governed reveal, FHIR lookup/rendering, legacy
migration, all-or-nothing rollback, idempotency, concurrent PostgreSQL writers,
and aggregate collector redaction/read-only enforcement. Clinical dispensing,
DHA, document encryption and static asset build regressions were also exercised.

Restricted local JUnit records and source hashes are stored under
`artifacts/generated/compliance/dpia-control-closure-2026-10-26/` (git ignored).
Exact results and limitations are in that folder's validation record. They are
engineering evidence, not production, issuer or independent-assessor approval.

The [closure register](20_DPIA_GAP_CLOSURE_REGISTER.md) remains open for Kenya
hosting, privileged MFA, an approved retention lifecycle, scanner disposition,
host/database/backup encryption and separate custody, full restore evidence,
independent assurance, DHA documentary scope and accountable risk sign-off.
