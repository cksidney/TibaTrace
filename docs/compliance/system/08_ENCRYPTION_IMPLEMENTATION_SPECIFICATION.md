# Encryption Implementation Specification

**Status:** As-built source specification with production evidence gaps<br>
**Production evidence:** rc71, `2965194a29311314e8a5772adfeee5af8c14a8f2`, 25 October 2026. **Source update:** commit `f8ea5cd`, local and not deployed, reviewed 26 October. See [current review](21_DPIA_CURRENT_REVIEW_2026-10-25.md) and [rollout guide](23_IDENTIFIER_KEY_REMEDIATION_AND_ROLLOUT.md).

## 1. Current controls

| Data/transport | Current implementation evidenced in source/docs | Limit |
|---|---|---|
| Public browser/API transport | HTTPS at Caddy; Django production settings enable redirect, HSTS, secure session/CSRF cookies and security headers | Live public HTTPS/certificate, HSTS, nosniff and frame denial observed; retest per deployment |
| PostgreSQL transport | Documented Esenai host requires PostgreSQL TLS; Django production expects secure production settings | Live TLS 1.3 observed with sslmode=require; hostname verification is not required by this setting; verify-full and trust-chain plan remain to assess |
| Patient identifiers | Deployed rc71 uses Fernet/HMAC with tenant binding; local commit `f8ea5cd` adds separate versioned encryption and lookup keyrings and legacy-compatible rotation | New keyring is not deployed or independently reviewed; provision, migrate, read back and recover before claiming production protection |
| Passwords | Django authentication password-hashing framework | Confirm deployed hasher configuration and upgrade policy from runtime settings |
| Windows POS credentials | Windows DPAPI protection is documented for native client credential material | Device recovery/rotation and local cache scope require client-specific validation |
| Android POS credentials | Android Keystore-backed token handling is documented; release cleartext is disabled | Confirm signing/release configuration and device reset/revocation behavior |
| Clinical attachments | Source now encrypts new object bytes with AES-256-GCM using an external, versioned keyring and the tenant/object key as authenticated context; SHA-256 verifies plaintext, reads remain capability/token/tenant-bound and audited | Live keyring valid; no stored clinical documents at audit, so no legacy migration/readback/rotation population to verify. Host/database at-rest and recovery/key custody remain open |
| Backups | Encrypted rc71 release DB/environment/clinical-object archives have verified inventories; backup key and archives are on the same VPS | Recurring coordinated schedule, separate protected copy/key custody, retention and full restore report remain open; owner says a separate restore exercise exists |
| Secrets | Production rejects unsafe default secret; secret file is outside releases and is documented with restrictive permissions | Runtime secret manager, access audit, rotation and break-glass process require operational evidence |

## 2. Patient identifier cryptography

The deployed rc71 implementation used:

1. Normalize the identifier by trimming, upper-casing and removing whitespace.
2. Derive a Fernet key from `SHA-256(SECRET_KEY + ":patient-identifier:" + tenant_id)`, URL-safe Base64 encoded. Fernet provides authenticated encryption with AES-128-CBC and HMAC-SHA256 through the `cryptography` library.
3. Derive a separate lookup digest using HMAC-SHA256 keyed by `SECRET_KEY + ":" + tenant_id`, over `identifier_type + ":" + normalized_value`.
4. Store ciphertext, digest and last four characters; clear the plaintext field. Decryption requires a separately authorized reveal workflow and records an audit event.

Because `SECRET_KEY` is a root dependency for this scheme and other Django functions, changing it without an explicit migration can make historical identifiers undecryptable and digests unmatchable. Do not rotate it as a routine text replacement.

## 3. Key management and rotation

Clinical-object keys are configured as a JSON key-ID map in the protected deployment secret file. The active key encrypts new objects; old key IDs must remain available to decrypt existing objects and retained backups. Changing the active key ID allows new writes to use a fresh key while reads continue to use old IDs. Before production certification or key rotation, the service owner must evidence:

- protected storage and access audit for the keyring, separate from source images and database/object volumes;
- named key owner, backup and recovery route, separation of duties, rotation triggers, revocation and compromise response;
- migration dry-run and integrity-checked object re-encryption using `migrate_clinical_objects_encryption`, with rollback from a verified database/object backup;
- evidence that old key IDs are retained for all encrypted objects and backups until their approved expiry;
- tested restore of encrypted data and re-encryption after restore where required;
- explicit key ownership when a tenant leaves service and lawful deletion/return process.

For rc71, patient identifier keys remain deterministically derived from Django `SECRET_KEY`; this is not a managed, versioned keyring. The local `f8ea5cd` implementation changes the source design but is not yet production evidence. Neither construction should be described as KMS-managed encryption.

### 26 October source remediation, not deployed

The local remediation replaces this patient-identifier root dependency with
independently provisioned versioned encryption and lookup keyrings, tenant/purpose
separation, explicit legacy compatibility and atomic tenant-scoped rotation. It
also protects direct FHIR writes and preserves external identifier namespace and
case. See [implementation and controlled rollout](23_IDENTIFIER_KEY_REMEDIATION_AND_ROLLOUT.md)
for configuration, tests and migration/rollback requirements. This does not
change the rc71 runtime evidence or close host/database encryption, separate key
custody, recovery or independent-review findings.

## 4. Clinical object encryption and legacy migration

`LocalClinicalObjectStorage` encrypts newly stored files using AES-256-GCM. The authenticated context binds ciphertext to its tenant-qualified object key. SHA-256 and stored size are checked after decryption, and replacement writes use an atomic temporary file with restrictive permissions. Document downloads continue to require signed actor/tenant-bound short-lived tokens and a read capability.

The deployment environment must provide a valid active keyring; production settings and the upload path fail closed without one. The migration command performs a complete integrity-checked dry run by default, then atomically encrypts legacy plaintext objects or rotates objects to the active key when run with `--apply`. It is idempotent and does not delete objects. The audit found no stored clinical objects, so no production migration was needed or claimed. Before using it for a future population, run only after a protected database/object backup and verify dry-run/apply, readback and key/backup retention. Application encryption does not prove that production or backup volumes are themselves encrypted; verify those separately.

Production requires CLEAN only when the required-scan policy is enabled. The current required-scan flag is false and no scanner endpoint is configured, following the earlier owner deferral; deferred uploads are NOT_SCANNED. This remains an open DPIA control gap, not a clean-scan result.

## 5. Cryptographic operations and approval

- Use approved libraries and algorithms; do not design custom encryption.
- Never log plaintext identifiers, secrets, access tokens, private key material or full clinical payloads.
- Keep encryption keys and backup keys separate from encrypted data and ordinary application credentials.
- Validate TLS certificates and modern protocol/cipher policy at the edge and database boundary.
- Document every key rotation before execution, with verified backup, dual-read strategy, canary, rollback and integrity checks.

**Security owner approval:** pending<br>
**Deployment evidence:** TLS and runtime object keyring verified in restricted packet; no stored objects at audit. Host/database at-rest proof, separate key custody, rotation/recovery, scanner operation and complete restore remain pending.
