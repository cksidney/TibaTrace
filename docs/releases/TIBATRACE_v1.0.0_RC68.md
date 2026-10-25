# TibaTrace 1.0.0-rc68 — tenant DHA integration, disabled by default

Adds tenant/branch DHA configuration, owner-reviewed activation, national registry
and terminology calls, consent and visit handling, reviewed prescription intake,
supply-derived FHIR exchange, claims adapters, callbacks and reconciliation.
The HQ National Integrations workspace exposes setup and approval blockers.

Connections start DISABLED. Deployment creates no tenant connections, credentials,
identity/product mappings or approval evidence. Missing credentials, encryption
keys, environment bindings, current connectivity validation or approval prevent
activation. Production API URLs have no default. Callback and retry execution
recheck tenant, branch, actor authority and activation. A minute-based queue task
handles only existing commands and cannot activate a tenant.

The deployed configuration keeps DHA environment bases empty and supplies no DHA
credentials or journal keys. Commission each tenant only after its verified
mappings, credentials, approved DPIA/security/UAT and DHA/facility approvals exist.
The existing malware-scan deferral policy is preserved without marking files clean.
Remittance routes and repeat-order balance contracts require DHA confirmation.

## Schema and recovery

One additive migration creates four new DHA tables and their constraints/index.
It does not migrate or change existing clinical, inventory or payment records.
Back up the database, protected environment and clinical-object volume before
activation. The rc67 application can operate with these unused additive tables
retained. Do not reverse/drop them after DHA evidence has been written.

## Release scope

This release isolates DHA changes and their required capability helper from the
separate local security/procurement drafts. It does not establish DHA certification
or close the outstanding system DPIA decision. Native POS installers are unchanged.

Require the exact-source SQLite/PostgreSQL suites, frontend gates, migration
evidence, image scans and signed build provenance before deployment. Then verify
source labels, health, migrations, worker registration, unchanged tenant business
data and zero active DHA connections or provider traffic.

[Activation guide](../integrations/DHA_TENANT_ACTIVATION.md).
