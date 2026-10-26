# rc75 production deployment — 26 October 2026

TibaTrace server release `1.0.0-rc75` is deployed and accepted at
`https://tibatrace.esenai.co.ke/`. Exact source:
`39f3e0651fc21f1e9f017db6e9bbaaf3992640bf`.

## Release evidence

[Production Images run 40295977977](https://github.com/cksidney/TibaTrace/actions/runs/40295977977)
passed the exact-source SQLite and PostgreSQL 16 business suites, coverage,
application gates, PostgreSQL synthetic recovery, dependency/runtime image scans,
startup checks, migration evidence, SBOM generation and image publication.
Each database suite accounted for all 2,546 tests exactly once. PostgreSQL had
zero failures/errors/skips; SQLite had three PostgreSQL-only skips and no
failures/errors.

The deployment operator verified all eleven release checksums, OCI source/version/architecture
and GitHub build provenance bound to the exact tag and commit. This is engineering
verification, not independent assessor approval.

| Component | Immutable digest |
|---|---|
| Backend | `ghcr.io/cksidney/tibatrace-backend@sha256:ca6e0518dd3522d569bbff25c69a55f46f15c8e384f58a1844b0be8c5fdb5311` |
| HQ | `ghcr.io/cksidney/tibatrace-hq-web@sha256:4729e560f494c3192d03bd03b8809f6283a66b9d07c992a5bfccd3f4b334461d` |

## Backup, migration and acceptance

The versioned backup runner captured a coordinated, encrypted database,
configuration and clinical-object recovery point with TibaTrace writers stopped.
Unchanged public POS installers were preserved on their existing volume and
excluded from the clinical-object archive. Ciphertext and manifest authentication,
full database archive parsing and decrypted tar inventories passed. The backup
runner resumed the old writers before the separate migration maintenance window.
These checks establish archive integrity; a full production-scope restore and
separate custody remain outstanding.

Writers were quiesced again. `identity.0003_mfacredential` created the empty MFA
credential table without rewriting existing users. Synthetic acceptance used a
temporary key only in its process, verified enrollment/local QR, protected seed
readback, session and JWT enforcement, single-use recovery, recovery replay denial,
and rejection of an older password-only refresh. Every synthetic database write
rolled back. Selected tenant, patient, prescription, stock and sales counts and
provider/DHA/connection states matched before and after migration and activation.
The live MFA credential table remained empty.

The first synthetic HTTPS sign-in lacked a browser Origin header and was
rejected. The acceptance script was corrected to send the same-origin header and
rerun successfully with CSRF enforcement enabled; application controls and source
were unchanged.

API, HQ and Redis health checks passed, the worker returned `pong`, and exactly one
scheduler was running. API, worker, scheduler and HQ identify the rc75 source.
Public HQ index/JavaScript/CSS bytes match the deployed image. Unauthenticated
patient and FHIR Patient requests were denied. The deployment pointer and GitHub
baseline were updated only after acceptance.

Protected evidence is retained at
`/opt/tibatrace/releases/tibatrace-1.0.0-rc75-39f3e065/acceptance/`.
An aggregate-only copy is in the git-ignored
`artifacts/generated/compliance/rc75-deployment-2026-10-26/` directory. Keys and
production configuration were not copied into the local evidence or source.

## Preserved activation constraints

- Malware scanning stays deferred: required-scan is false and RX source uploads
  stay enabled. Deferred uploads retain `NOT_SCANNED` provenance.
- No national/DHA provider, tenant DHA connection, RX feed or checkout integration
  is active. Requested provider drafts are preserved.
- MFA enforcement is false, its keyring remains unconfigured, and no live account
  was enrolled. The new code is available for the approved supervised rollout.
- Identifier/document keys and historical compatibility keys are unchanged.
  Published POS installers and client minimums are retained. Signed/installed
  compatible native clients still need acceptance before POS MFA activation.
- No recurring backup timer, external audit destination, retention/deletion job
  or scanner was activated.

The actual previous release and rollback images are rc74,
`27469e1993d85606001787fb058052fe1cb6b4b6`, captured in
`PREVIOUS_RELEASE.json`; its protected environment is retained. Ignore the
historical alpha placeholders in the generated manifest. The migration is
additive. Do not restore an older database over accepted transactions. Once MFA
enrollment occurs, an old binary does not enforce the new requirement and any
rollback requires a reviewed authentication/recovery decision.

The system DPIA remains **NOT APPROVED**. Use the
[owner evidence and approval checklist](../compliance/system/26_OWNER_EVIDENCE_AND_APPROVALS_REQUIRED.md)
for hosting, retention, independent assurance, MFA activation/custody, recovery,
audit/incident, scanner-deferral and accountable sign-off requirements.
