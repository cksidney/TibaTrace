# TibaTrace 1.0.0-rc75 — technical DPIA controls

This release deploys the tested MFA/recovery, access-review, audit checkpoint,
authenticated backup and synthetic recovery controls described in
[technical delivery](../compliance/system/25_TECHNICAL_DPIA_CONTROL_DELIVERY_2026-10-26.md).
The prior production baseline is rc74,
`27469e1993d85606001787fb058052fe1cb6b4b6`.

## Release scope

- HQ authenticator enrollment/confirmation, encrypted versioned MFA seeds,
  persisted guessing limits, replay rejection, single-use recovery codes,
  session/JWT/refresh enforcement and governed reset/key rotation.
- Restricted account/session access-review snapshots, signed audit checkpoints
  with separately trusted verification keys, and an authenticated coordinated
  backup runner. Operations still must approve their destinations, custody,
  schedules and recovery requirements before activating recurring jobs.
- A synthetic PostgreSQL recovery rehearsal included in the production-major
  release gate. This does not replace a witnessed production-scope restore.
- Compatible Electron/Vite/Vitest and transitive dependency patches. The existing
  narrow Metro image-size build-tool exception remains documented.

Windows/Android source accepts OTP/recovery input and saves renewed sessions only
after matching the current operator and tenant. Server deployment does not replace
installed native binaries. Retain the published installers and client minimums;
release and verify compatible native packages before MFA activation for POS users.

## Activation constraints

Preserve the reviewed live settings:

- `DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED=false`;
- `DAWATRACE_RX_SOURCE_UPLOADS_ENABLED=true`;
- no active national/DHA providers or tenant DHA connections;
- empty/disabled `TIBATRACE_RX_CONNECTIONS` and
  `TIBATRACE_CHECKOUT_CONNECTIONS`; and
- `TIBATRACE_PRIVILEGED_MFA_REQUIRED=false` during the staged rollout.

Keep independent MFA encryption keys unconfigured until the supervised
enrollment/key-custody and compatible-client plan is approved. The source is
deployed for activation; this release does not claim that administrators have
enrolled or that privileged MFA is enforced. An account that later enrolls remains
MFA protected through reset, even during optional rollout.

No scanner, integration, recurring backup timer, external audit destination or
retention/deletion job is activated by this release. Deferred attachments retain
`NOT_SCANNED` provenance. The approved identifier/document keyrings and all
historical compatibility keys must be preserved.

## Migration and recovery

`identity.0003_mfacredential` creates an empty MFA credential table. It performs no
existing-user enrollment or data rewrite. Verify the exact tagged image's plan and
inventory against rc74 before applying. Quiesce TibaTrace writers and take a
protected encrypted database/configuration/clinical-data backup before migration.
Verify archive authentication/integrity and preserve the actual rc74 images and
environment as the rollback reference.

The migration is additive. Do not reverse schema or restore a pre-release database
over accepted transactions. Once enrollment occurs, an older binary does not
enforce the new MFA requirement; application rollback therefore also requires a
reviewed authentication/recovery decision. This deployment keeps enrollment and
enforcement inactive and verifies that the credential table remains empty.

## Acceptance

Require exact-tag Production Images success, signed provenance, verified immutable
digests/checksums, PostgreSQL 16 suites and synthetic recovery, frontend gates,
startup/migration checks and dependency/container scans. Deploy only those digests.

After migration and before reopening writes, use rolled-back synthetic acceptance
to verify MFA enrollment/recovery, protected seeds, refused replay, password-only
clinical/admin denial and unchanged provider/scan configuration. Use temporary
synthetic runtime keys for this acceptance without configuring live enrollment.
Confirm all synthetic rows rolled back and all business counts remain unchanged.

Check API/HQ/Redis health, worker response, one scheduler, uniform source identity,
public HQ assets and unauthenticated clinical access denial. Record migration,
MFA-unconfigured predicates, integration states, backup/recovery references and
the accepted deployment baseline. The DPIA remains **NOT APPROVED**; the
[owner evidence checklist](../compliance/system/26_OWNER_EVIDENCE_AND_APPROVALS_REQUIRED.md)
still governs the outstanding decisions and artifacts.
