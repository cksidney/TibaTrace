<!-- TIBATRACE DOCUMENT BRANDING START -->
<p><img src="../brand/tibatrace-logo.jpeg" alt="TibaTrace logo" width="150"> &nbsp; <img src="../brand/esenai-group-logo.png" alt="Esenai Group logo" width="200"></p>

**TibaTrace · Esenai Group Ltd**<br>
Branding edition: 26 October 2026. Assessment dates, evidence scope and approval decisions below remain controlling.
<!-- TIBATRACE DOCUMENT BRANDING END -->

# Audit Trail Specification

**Status:** As-built application specification; production retention/export controls require confirmation; reviewed 26 October 2026<br>
**Source:** `backend/apps/audit/`, `backend/apps/documents/`, domain audit services

## 1. Purpose

Audit records provide attributable evidence of selected user, platform, clinical, financial, configuration and document actions. They support investigation and accountability. They are not a complete operating-system, database-administrator, reverse-proxy or cloud audit stream.

## 2. Core event records

| Record | Scope | Fields and behavior |
|---|---|---|
| `AuditEvent` | Tenant action | Tenant, actor (nullable after user removal), action, model name, object ID, correlation ID, outcome, metadata and timestamp; tenant-scoped indexes; application save/delete methods prevent update/deletion |
| `PlatformAuditEvent` | Explicit platform-owner action | Actor, action, model name, object ID, correlation ID, outcome, metadata and timestamp; write service requires an active explicit platform admin/superuser; application save/delete methods prevent update/deletion |
| `DocumentAccessEvent` | Clinical attachment | Tenant, document, actor, action (`UPLOAD`/`DOWNLOAD`), outcome (including integrity mismatch), and timestamp |
| Domain events/ledger records | Specific business workflows | Separate immutable/state-machine evidence may exist for payments, dispensing, stock ledger, POS shifts, recalls, integrations and configuration; consult each domain specification |

Audit immutability is enforced at the application model/service boundary. A sufficiently privileged database or host administrator could alter underlying storage; cryptographic chaining, external WORM archival, and independent log-signing are not established by the inspected source.

## 3. Events to record

Record at least: successful and denied authentication/security changes; user/role/capability grants/revocation; tenant and branch changes; sensitive identity reveal; patient or practitioner create/update/verification; clinical review, override and dispensing; payment collect/refund/void/reconciliation; inventory receipt/transfer/adjustment/recall/quarantine/release; document upload/download/integrity failure; provider activation/callback/reconciliation; privileged platform action; export/report generation and administrative configuration changes.

Each event should have an authenticated actor (or explicitly named service identity), tenant if applicable, timestamp, action, target object, result, reason/evidence where required, and request/correlation identifier. Do not copy full patient records, passwords, tokens or payment credentials into metadata.

## 4. Access, review and retention

- Audit access is capability controlled and tenant scoped; platform-wide records are restricted to explicit platform-owner authority.
- Review high-risk access, denied cross-tenant requests, privileged changes, identifier reveals, suspicious payment events, and integration status changes.
- Exported audit data must retain tenant scope, time range, filters, exporting actor and hash/checksum where provided.
- Define and enforce audit retention, backup, export, legal hold and secure disposal under the approved retention schedule. The source does not establish a single audit retention period.
- Forward infrastructure and security logs to an independently protected, time-synchronized log system. No tamper-evident remote log sink was confirmed in this review.

## 5. Integrity and operational requirements

Use UTC-capable timestamps with the deployment timezone configured consistently; preserve original correlation IDs when events cross jobs. Monitor write failures. A failure to write a mandatory audit record should block the associated sensitive state transition where the domain service requires atomicity. Reconcile domain ledgers against audit events during incident review; the audit table is not the only financial or stock record.

## 6. Evidence and limitations

The rc71 release evidence and application checks provide release-specific evidence for the audited server. They do not demonstrate external immutable storage, ongoing audit review, retention enforcement, or complete coverage of every read request. Build an event-to-control matrix from the exact release and confirm every high-risk action is covered before relying on the audit trail for certification.


## 26 October source checkpoint tooling

`python manage.py audit_checkpoint` produces a restricted Ed25519 signed
checkpoint over ordered audit-table content hashes, with optional previous-file
linkage and a separately trusted public-key verification command. Raw clinical
metadata and object/actor references are not exported. This is new source work,
not evidence of deployed external log protection. A signature protects the
checkpoint; privileged source deletion before generation remains outside its
assurance. Separate custody, continuity checks, database roles and monitored
append-only delivery still require operational acceptance. See
[technical delivery](25_TECHNICAL_DPIA_CONTROL_DELIVERY_2026-10-26.md).
