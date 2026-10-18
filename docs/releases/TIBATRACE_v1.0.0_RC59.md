# TibaTrace 1.0.0-rc59 — RX intake with explicit scanning deferral

Windows POS 1.0.14 (build 14) carries direct prescription intake, photo/PDF
sources and governed clinical review from rc58. At the operator's request,
malware scanning can be explicitly deferred in deployment configuration.
Uploaded sources retain `NOT_SCANNED` status, audit provenance and a visible POS
notice. They are never marked clean by this mode. File validation, tenant and
role checks, document encryption and pharmacist review remain enforced.

Configure `DAWATRACE_RX_SOURCE_UPLOADS_ENABLED=true` and
`DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED=false` for the requested deferred mode.
The default policy still requires scanning. To enable ClamAV later, commission
the private endpoint and restore the required flag. Existing unscanned objects
must be assessed separately; enabling scanning does not certify earlier uploads.
Application-generated JSON records carry distinct `NOT_APPLICABLE` provenance.

Repairs the merged demo validator's tenant-scoped audit query and stale test
fixtures, and reconciles migration evidence with the unified fiscal architecture
and prescription migrations 0019/0020. No additional schema changes over rc58.
Tenant EMR/DHA, card and Daraja integrations still require commissioning.

Activation requires exact-source SQLite/PostgreSQL and application release gates,
immutable CI image digests, signed Windows installation acceptance and protected
database/object/environment backups. Keep rc57 recovery metadata and document
keys. After encrypted-document writes, recovery must use a compatible forward
fix or a reviewed plan; rc57 cannot read the new encrypted objects.
