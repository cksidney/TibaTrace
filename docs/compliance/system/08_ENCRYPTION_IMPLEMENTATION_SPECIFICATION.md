# Encryption Implementation Specification

**Status:** As-built source specification with production evidence gaps  
**Source snapshot:** working tree based on `45bf133`, 17 October 2026; the object-encryption code described here is an unshipped local change and has no production release evidence

## 1. Current controls

| Data/transport | Current implementation evidenced in source/docs | Limit |
|---|---|---|
| Public browser/API transport | HTTPS at Caddy; Django production settings enable redirect, HSTS, secure session/CSRF cookies and security headers | Verify active DNS, Caddy, certificates, TLS policy and headers per deployment |
| PostgreSQL transport | Documented Esenai host requires PostgreSQL TLS; Django production expects secure production settings | Retain active connection/DB TLS evidence and certificate validation configuration |
| Patient identifiers | `PatientIdentifierProtector` normalizes values; Fernet encrypts the value; HMAC-SHA256 digest supports lookup; plaintext value is cleared; UI keeps last four | Key is deterministically derived from Django `SECRET_KEY` and tenant ID; no separate KMS/HSM/versioned key ring is evidenced |
| Passwords | Django authentication password-hashing framework | Confirm deployed hasher configuration and upgrade policy from runtime settings |
| Windows POS credentials | Windows DPAPI protection is documented for native client credential material | Device recovery/rotation and local cache scope require client-specific validation |
| Android POS credentials | Android Keystore-backed token handling is documented; release cleartext is disabled | Confirm signing/release configuration and device reset/revocation behavior |
| Clinical attachments | Source now encrypts new object bytes with AES-256-GCM using an external, versioned keyring and the tenant/object key as authenticated context; SHA-256 verifies plaintext, reads remain capability/token/tenant-bound and audited | Production key provisioning and rotation evidence are not attached. Legacy objects remain readable for migration and are not encrypted until `migrate_clinical_objects_encryption --apply` is run and verified. Host-volume and backup encryption remain independent requirements |
| Backups | rc52 record documents a pre-deployment database backup with integrity/restore-inventory checks | Recurring backup encryption, key custody, off-host copy, retention and full restore exercise are not proven by that release record |
| Secrets | Production rejects unsafe default secret; secret file is outside releases and is documented with restrictive permissions | Runtime secret manager, access audit, rotation and break-glass process require operational evidence |

## 2. Patient identifier cryptography

The source implementation uses:

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

Patient identifier keys remain deterministically derived from Django `SECRET_KEY`; this is not a managed, versioned keyring. The attachment keyring does not close that separate key-lifecycle finding. Do not describe either construction as KMS-managed encryption.

## 4. Clinical object encryption and legacy migration

`LocalClinicalObjectStorage` encrypts newly stored files using AES-256-GCM. The authenticated context binds ciphertext to its tenant-qualified object key. SHA-256 and stored size are checked after decryption, and replacement writes use an atomic temporary file with restrictive permissions. Document downloads continue to require signed actor/tenant-bound short-lived tokens and a read capability.

The deployment environment must provide a valid active keyring; production settings and the upload path fail closed without one. The migration command performs a complete integrity-checked dry run by default, then atomically encrypts legacy plaintext objects or rotates objects to the active key when run with `--apply`. It is idempotent and does not delete objects. The command has not been run against production in this assessment. Run it only after a protected database/object backup, then verify the dry-run/apply record, readback and key/backup retention. Application encryption does not prove that production or backup volumes are themselves encrypted; verify those separately.

Production attachment uploads also fail closed unless a configured malware scanner returns `CLEAN`; the inspected default scanner returns `NOT_CONFIGURED`.

## 5. Cryptographic operations and approval

- Use approved libraries and algorithms; do not design custom encryption.
- Never log plaintext identifiers, secrets, access tokens, private key material or full clinical payloads.
- Keep encryption keys and backup keys separate from encrypted data and ordinary application credentials.
- Validate TLS certificates and modern protocol/cipher policy at the edge and database boundary.
- Document every key rotation before execution, with verified backup, dual-read strategy, canary, rollback and integrity checks.

**Security owner approval:** pending  
**Deployment evidence attached:** pending (TLS configuration, production keyring/custody, legacy migration, host/database/backup encryption, backup restore and rotation exercise)
