# TibaTrace 1.0.0-rc73 — independent patient identifier keyrings

This release adds independent, versioned encryption and lookup keyrings for
patient identifiers, tenant-scoped key derivation, explicit legacy compatibility,
and controlled identifier rotation. FHIR identifier intake and reference lookup
use the protected identifier service. The source change is included in this
release candidate; it is not production behavior until this exact release passes
all release gates and is deployed.

## Database and key configuration

Migration `patients.0003_patientidentifier_lookup_key_id` adds the lookup-key
version field. It does not itself decrypt or rewrite existing identifier rows.
The application requires valid, distinct encryption and lookup keyrings in
production settings before it starts.

Before deployment, create separate random 32-byte keys for each purpose and
store them only in the protected production secret file or approved secret
manager. Configure:

- `DAWATRACE_PATIENT_IDENTIFIER_KEYS` and
  `DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID`;
- `DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS` and
  `DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID`; and
- `DAWATRACE_PATIENT_IDENTIFIER_LEGACY_SECRET_KEYS` with each historical
  application secret still needed to read existing records or retained backups.

Do not reuse key material between the encryption and lookup rings. Retain old
keys for every identifier and backup that still depends on them. Run
`rotate_patient_identifier_keys --tenant-id <tenant-id>` first as a read-only
dry run for each tenant. Apply only after a verified database/environment/object
backup, a reviewed migration plan and explicit approval. The command reports
counts only and performs an atomic tenant-scoped rotation with `--apply`.

## Integration and client scope

DHA/national-provider, prescription-feed and checkout integrations remain
disabled unless separately configured and approved per tenant. This release
does not enable live integrations or certify TibaTrace. No Windows or Android
installer change is included.

The existing malware-scan deferral remains a separate open control gap. The
reviewed live configuration keeps
`DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED=false` and
`DAWATRACE_RX_SOURCE_UPLOADS_ENABLED=true`. This release preserves that state:
deferred attachments remain `NOT_SCANNED`, never `CLEAN`, with the existing user
notice and audit provenance. No scanner is installed or activated by this release.

## Release and production acceptance

Require the exact-tag Production Images workflow to pass its SQLite and
PostgreSQL business suites, application checks, dependency and image scans,
migration inventory, startup checks, SBOM generation and signed build provenance.
Publish/deploy only the resulting immutable image digests.

Before activation, verify an encrypted and checksummed backup of the production
database, protected environment and clinical-object volume; verify the current
identifier-row count and legacy-key requirements without exporting identifiers.
Deploy the key configuration before starting the new API. Apply the additive
schema migration, verify service/worker health, current migrations, FHIR behavior,
identifier create/lookup/reveal under authorized synthetic cases, tenant
isolation, and zero unintended DHA/RX/checkout connections. Record the image
digests, environment key IDs (never key values), migration result, backup,
rollback target and acceptance evidence. Do not claim a DPIA pass from this
release; the [system DPIA](../compliance/system/01_DATA_PROTECTION_IMPACT_ASSESSMENT.md)
remains not approved until its separate evidence and approval gates are closed.
