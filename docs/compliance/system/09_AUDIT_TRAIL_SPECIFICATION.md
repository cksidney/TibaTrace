# Audit Trail Specification

**Status:** As-built application specification; production retention/export controls require confirmation  
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

The rc52 release evidence and application tests provide release-specific evidence of tenant and owner route behavior. They do not demonstrate external immutable storage, ongoing audit review, retention enforcement, or complete coverage of every read request. Before certification, build an event-to-control matrix from the current code and confirm every high-risk action is covered.
