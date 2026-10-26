# Technical DPIA control delivery — 26 October 2026

**Status:** Engineering changes under validation; not deployed or independently assessed.<br>
**Current production:** rc74, `27469e1993d85606001787fb058052fe1cb6b4b6`.<br>
**DPIA decision:** NOT APPROVED.<br>
**Operator constraints:** Malware scanning stays deferred. DHA, national-provider,
EMR/RX-feed, payment and tax integration activation stays disabled.

## Delivered controls

| Finding | Engineering delivery | Operational evidence still required |
|---|---|---|
| DPIA-09 | HQ authenticator enrollment/confirmation; encrypted versioned seeds; replay rejection; persisted account throttling; single-use recovery hashes; password plus second factor for reset/recovery regeneration; session/JWT/refresh enforcement; stale-proof revocation; temporary-password and admin-route guards | Exact-source release gates, separate MFA encryption keys, confirmed privileged-account enrollment, recovery custody, approved enforcement change and recurring access review |
| DPIA-09 | Windows/Android password sign-in and workstation unlock can supply an optional OTP/recovery code; MFA-protected users cannot use PIN sessions to bypass the second factor | Signed/released native clients, device install/upgrade evidence and actual login/unlock checks. Existing installed packages do not gain this source change automatically |
| DPIA-08/09 | Atomic MFA seed rewrap with retained keys; governed console reset requiring a different platform operator and references to approval/identity evidence | Verify the actual approval and identity-check records, key custodians, retained backup keys, compromise response and witnessed recovery |
| DPIA-09 | Restricted account/role/MFA and POS-session review export; no password, seed, recovery code or token hashes exported | Named reviewer decisions, resolved leaver/privilege/device findings and approved review frequency |
| DPIA-10 | Ed25519 signed audit checkpoint with cumulative ordered content hashes, previous-checkpoint linkage and separate trusted-public-key verification; clinical metadata stays out of the exported checkpoint | Approved separate signing-key custody, protected external append-only destination, delivery monitoring, continuity/source completeness checks and operating evidence |
| DPIA-11 | Versioned backup runner with writer quiescing/resume, encrypted DB/config/clinical archives, ciphertext and manifest authentication, verification-only mode and no automatic pruning | Approved destination, separate recovery-key custody, recurring schedule, monitoring, maintenance window, capacity, retention and full isolated production-scope restore |
| DPIA-08/11 | Synthetic PostgreSQL recovery runner restores the database, encrypted objects, identifier lookup keys and MFA seeds after removing the originals; rejects wrong keys/tampered archives; provider configurations remain absent | Exact production-major CI result, independently witnessed production-scope recovery, measured/approved RPO/RTO, separate failure-domain recovery and restoration of applicable holds/deletions |
| DPIA-03/10 | Compatible dependency patches for Electron, Vite/Vitest and affected transitive packages; security audit remains fail-closed for unexpected severe findings | Release/native installation and independent assessor scope; one narrowly allowed Metro `image-size` build-tool issue remains pending a compatible upstream fix |

Source controls are not live protection until a validated release and its
configuration are deployed. No live MFA flag, scanner setting or tenant
integration was activated by this engineering work.

## MFA activation procedure

1. Complete release CI, security review, backup and normal additive migration
   acceptance. Retain the tested previous deployment and coordinated recovery
   point. Review all accounts with `is_staff`, `is_superuser`,
   `is_platform_admin` or effective `identity.manage`; those are the privileged
   scope of the enforcement flag.
2. Provision `TIBATRACE_MFA_ENCRYPTION_KEYS` and
   `TIBATRACE_MFA_ACTIVE_KEY_ID` in protected runtime storage. Each key is a
   separately generated base64url 32-byte value. Do not reuse document,
   identifier-encryption or identifier-lookup keys. Production settings reject
   reused/malformed keyrings when MFA keys or enforcement are configured.
3. Deploy with `TIBATRACE_PRIVILEGED_MFA_REQUIRED=false` during supervised
   enrollment. An account that enrolls must use MFA thereafter even while this
   rollout flag is false. Have at least two named platform operators available
   and verify the governed lost-authenticator route before rollout.
4. In HQ, open the account menu → **Authenticator & recovery codes**. Confirm the
   current password, scan the locally rendered QR or enter its setup key, and
   confirm a fresh code. Store the ten single-use recovery codes securely and
   separately from the authenticator; do not send them to support, chat or email.
5. Verify authenticator sign-in, one recovery-code sign-in, replay rejection,
   recovery-code regeneration, session revocation and approved reset using
   designated test accounts. A second factor is required before changing a
   temporary password on an already enrolled account. Password reset never
   removes MFA.
6. Release/install the updated native clients for users who use POS with MFA.
   Supply OTP/recovery codes on password sign-in and unlock. PIN sessions cannot
   replace MFA. Record versions and device checks before enforcement.
7. Use the restricted access snapshot to confirm every active privileged account
   is enrolled. Obtain the owner/security enforcement approval and named recovery
   custodians; then set `TIBATRACE_PRIVILEGED_MFA_REQUIRED=true` by a recorded
   release/configuration change. Recheck that old password-only browser/access/
   refresh tokens cannot reach clinical/admin endpoints.
8. Capture live aggregate runtime evidence and a signed access-review decision.
   TOTP is a second factor, not phishing-resistant WebAuthn. Consider hardware
   security keys separately for higher-assurance privileged access.

MFA endpoints are cookie/session and CSRF protected. Secret-bearing responses use
`Cache-Control: no-store`. Enrollment is bound to the browser session and expires
after ten minutes. Proofs expire after twelve hours; fresh password sign-in is
required to verify again. Codes are accepted within one 30-second step of clock
drift and can be used only once. Server/device time synchronization must be
monitored.

```sh
# Restricted export; does not approve, revoke, or change accounts.
python manage.py access_review_snapshot --output /protected/review-YYYYMMDD.json

# Default is a dry run. Check the referenced approvals before --apply.
python manage.py reset_mfa --user-id USER_ID --operator-id DIFFERENT_PLATFORM_USER_ID \
  --approval-reference APPROVED_TICKET --identity-check-reference VERIFIED_RECORD

python manage.py rotate_mfa_keys --operator-id PLATFORM_USER_ID \
  --approval-reference APPROVED_ROTATION
```

Do not use password reset or disable the enforcement flag as a lost-device
workaround. Governed reset revokes existing proofs and requires enrollment again
where the policy applies. These console commands require trusted infrastructure
access; supplying a ticket reference does not itself prove that it was approved.

## Backup and audit operations

[`backup-runtime.py`](../../../deploy/tibatrace/backup-runtime.py) defaults to a
dry run. Provision a protected, single-line base64url recovery passphrase with at
least 32 independently random bytes. Keep it outside the backup destination and
under approved separate custody. The backup combines AES-256-CBC/PBKDF2 encryption
with purpose-separated HMAC-SHA256 authentication of every ciphertext and the
manifest. Verify authentication before recovery; never decrypt a modified or
unauthenticated archive. This new runner is not claimed to have run in production.

```sh
python3 backup-runtime.py --recovery-key-file /protected/backup.key \
  --output /approved-backup-target/NEW_RECOVERY_POINT
# --apply stops only TibaTrace writers and resumes them even on failure.

python3 backup-runtime.py --recovery-key-file /protected/backup.key \
  --output /approved-backup-target/EXISTING_RECOVERY_POINT --verify-only
```

Database archive parsing and object inventories are integrity checks. They do not
measure a complete recovery. Approve the recurring schedule, target and recovery
test before installing a timer/job. No backup or clinical/financial record is
automatically deleted by these changes.

For signed audit checkpoints, provision a separate owner-only Ed25519 seed file
and keep its public verification key under independently trusted custody. Do not
use the public key contained in an untrusted checkpoint as its trust anchor.

```sh
python manage.py audit_checkpoint --signing-key-file /protected/audit-signing.key \
  --output /protected/checkpoint-YYYYMMDD.json
python manage.py audit_checkpoint --verify /protected/checkpoint-YYYYMMDD.json \
  --trusted-public-key-file /independent-custody/audit-signing.pub
```

A signature detects modification of the exported checkpoint. It does not prevent a
privileged database user deleting events before checkpoint creation. Store prior
checkpoints separately, approve continuity/source checks, protect database roles
and configure external audit delivery before treating DPIA-10 as closed.

## Recovery rehearsal and limitations

[`dpia_recovery_rehearsal.py`](../../../scripts/dpia_recovery_rehearsal.py) creates
its own private PostgreSQL cluster with TCP disabled and synthetic data only. It
accepts no production connection string, environment file or backup. Its child
environment excludes provider credentials. Reports contain aggregate outcomes;
generated seeds, keys, dumps, objects and logs stay in protected local storage.
The CI job uploads only `REPORT.json`.

Run with PostgreSQL 16 to match production. A local PostgreSQL 18 run is explicitly
labeled as a different major and cannot substitute for the release gate or an
independent witnessed production restore. The synthetic exercise does not prove
provider egress fencing, production data completeness, retention reconciliation,
off-site custody or business RPO/RTO.

## Engineering validation record

Local frontend suites passed 518 tests across HQ (121), shared (216), Windows
(140) and Android (41). All three application typechecks and builds passed.
Desktop dark-theme enrollment and mobile light-theme recovery were rendered
with synthetic responses; no page errors or horizontal overflow were observed.
The backend authentication/password/admin regression run passed its 86
non-migration cases. All 16 migration-evidence tests passed after keeping the new
OTP dependency out of migration-only import paths. The focused operations suite
passed five tests for governed reset, seed rewrap, private access export, audit
signature modification and backup authentication. Runtime collector tests passed
11 cases, with its PostgreSQL-only control skipped locally under SQLite.

The isolated synthetic PostgreSQL 18 rehearsal restored DB, objects and identifier/
MFA keys, matched before/after checks and rejected wrong keys/tampering. Its
2.913-second synthetic restore measurement is not a production RTO; production
RPO/RTO and separate custody were not measured or proved. PostgreSQL 16 CI and
its row-lock/concurrency checks remain required before release. New final
regression results and exact-source CI are recorded separately in restricted
engineering evidence; do not treat this source document as an independent
assessment.

The dependency gate reports only the existing narrowly allowed Metro image-size
build-tool advisories. Runtime/native patches still require release and device
acceptance. No independent penetration assessment is claimed.

## Evidence and approvals

Use the [owner evidence checklist](26_OWNER_EVIDENCE_AND_APPROVALS_REQUIRED.md).
The remaining action plan and finding register stay open. In particular, the
unapproved seven-year triggers do not authorize irreversible deletion, and
scanner deferral requires a recorded risk treatment rather than a false clean
scan result.

Implementation references: [PyOTP security guidance](https://pyauth.github.io/pyotp/)
and the project's existing deployment, encryption and audit specifications.
