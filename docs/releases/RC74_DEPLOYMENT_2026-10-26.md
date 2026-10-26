# rc74 production deployment — 26 October 2026

TibaTrace server release `1.0.0-rc74` is deployed and accepted at
`https://tibatrace.esenai.co.ke/`. The exact source is
`27469e1993d85606001787fb058052fe1cb6b4b6`.

## Release evidence

[Production Images run 40251366852](https://github.com/cksidney/TibaTrace/actions/runs/40251366852)
passed all eight SQLite quality shards, all eight PostgreSQL business shards,
coverage, application gates, dependency and runtime image scans, startup checks,
migration evidence, SBOM generation and image publication. GitHub build provenance
was verified by the deployment operator for both digests and binds
them to the exact rc74 tag and source. This provenance verification is an
engineering check; no independent security-assessor approval is implied.

| Component | Immutable digest |
|---|---|
| Backend | `ghcr.io/cksidney/tibatrace-backend@sha256:2ec6339d8c5a8f590b7f02ebf7d2ca628eb2b136934e8421b94d8673825264a9` |
| HQ | `ghcr.io/cksidney/tibatrace-hq-web@sha256:341f6ed1302fd470d3e49b633be711fe8e3d61260a429850ace5e24574899d9b` |

The downloaded release evidence passed all eleven checksums. OCI version,
architecture and source labels matched the manifest and running containers.
The deployment baseline and `/opt/tibatrace/current` now identify rc74.

## Migration and key acceptance

Writers were stopped for a coordinated encrypted database, configuration and
clinical-data backup. Public POS installers were preserved on their existing
volume and excluded from the clinical-data archive. The database archive was
parsed completely and decrypted tar inventories verified. These checks establish
archive integrity; they are not a full restore exercise.

`patients.0003_patientidentifier_lookup_key_id` applied successfully. It adds one
field and performs no data rewrite. Separate random 32-byte encryption and lookup
keys were provisioned in protected runtime configuration. The historical service
secret was retained only for legacy identifier reads. API, worker and scheduler
receive matching keyrings. Key values were not printed or put in source control.

There were no stored patient identifiers to rotate. Read-only preflight succeeded
for each existing tenant. Synthetic acceptance verified encrypted storage with
cleared plaintext, protected readback, masking, exact case/namespace lookup,
cross-tenant lookup/decrypt denial, protected FHIR rendering and rejection of a
mismatched FHIR tenant context. Every synthetic database write was rolled back.
Selected patient, prescription, stock and sales counts matched before and after.

## Live acceptance and recovery

API, HQ and Redis health checks passed; worker ping returned `pong`; exactly one
scheduler is running. API, HQ, worker and scheduler report the same rc74 source,
with zero restarts at acceptance. Public HQ index, JavaScript and CSS bytes match
the deployed HQ image. Unauthenticated patient and FHIR Patient requests return
HTTP 401. The API's database-backed public health returns HTTP 200.

A second encrypted recovery backup includes the new key configuration. Decrypted
environment readback matched the exact active configuration without disclosing
its contents. Pre- and post-deployment backups and their recovery keys remain on
the same host; separate custody and a full witnessed restore remain open.

Protected production evidence is under
`/opt/tibatrace/releases/tibatrace-1.0.0-rc74-27469e19/acceptance/`.
An aggregate-only local copy is retained in the git-ignored
`artifacts/generated/compliance/rc74-deployment-2026-10-26/` directory.

The previous production release is rc71,
`2965194a29311314e8a5772adfeee5af8c14a8f2`; its images and environment were retained.
Use this captured production rollback target rather than the historical alpha
placeholder in the generated manifest. Old application code cannot read rc74
identifier ciphertext. Any rollback must follow the
[identifier rollout procedure](../compliance/system/23_IDENTIFIER_KEY_REMEDIATION_AND_ROLLOUT.md)
and account for schema and accepted writes; do not blindly restore old data.

## Remaining control gaps

DHA/national-provider, RX-feed and checkout integrations remain disabled. RX source
uploads retain the approved scan deferral: scanning is not required, and deferred
files retain `NOT_SCANNED` provenance. The aggregate collector confirms valid
independent identifier keyrings and database TLS 1.3, and reports the deferred
scanner as an observed control gap.

The system DPIA remains **NOT APPROVED**. This deployment supplies evidence for
part of DPIA-08. Hosting/localization, retention approval and lifecycle,
privileged MFA, scanner operation, storage encryption and separate key custody,
full recovery, independent assurance and accountable approval remain subject to
the [remaining action plan](../compliance/system/24_DPIA_REMAINING_ACTION_PLAN_2026-10-26.md).
