# TibaTrace DPIA: current evidence and closure decision

**Review date:** 25 October 2026, Africa/Nairobi<br>
**Assessment:** system/provider DPIA v0.4<br>
**Decision:** NOT APPROVED; remediation and accountable review required<br>
**Accountable owner:** Esenai Group Ltd; owner-nominated approval owner Sidney Chepkwony

**Record integrity note:** This document remains the dated 25 October production-evidence snapshot. Local source commit `f8ea5cd` and the 26 October document updates do not amend its rc71 facts. See the [remaining action plan](24_DPIA_REMAINING_ACTION_PLAN_2026-10-26.md) for later source status and next steps.

## Evidence established

The operator's local incorporation certificate names ESENAI GROUP LTD, company
`PVT-LRUX9R6`, incorporated 8 November 2020. The matching ODPC certificate names
the company as Data Processor `890-695D-435E`, serial 31078, valid 15 October 2026
through 15 October 2028. Both were rendered and visually reviewed; copies and
hashes are in the restricted packet. This is documentary corroboration, not an
issuer online verification or approval of this DPIA. The owner supplied a privacy
contact and nominated an approval owner; contact/appointment and final sign-off
remain separate checks.

The deployed server release is `1.0.0-rc71`, commit
`2965194a29311314e8a5772adfeee5af8c14a8f2`. All four server services match it:

| Image | Immutable digest |
|---|---|
| Backend, worker, scheduler | `sha256:a3ed4bd1f5a6b8458dffddc393909aa8fb4ebb8cd1f6a78ea48689f80d47c80c` |
| HQ static web | `sha256:bcb682252abde0e55dce57cf2c6f833c84119c6f3eca66913732c18fd17481ea` |

[CI run 40169584453](https://github.com/cksidney/TibaTrace/actions/runs/40169584453)
passed every application, SQLite/PostgreSQL shard, exact-coverage and image job.
Release checksums and both image attestations were verified against the tag and
commit. Both runtime scans contain zero HIGH/CRITICAL findings; the backend report
contains one UNKNOWN advisory without detail, so it is not a zero-finding report.
No independent penetration-test conclusion is inferred. The native POS installed
versions/device stores were not examined in this review.

The aggregate collector ran against production in a PostgreSQL repeatable-read,
read-only transaction. It exports no patient rows, identifiers, object bytes,
secret values, tenant names or account names and makes no provider/scanner calls.
Restricted reports contain current aggregate scale, demo designation, age bands,
account counts, activation states and configuration predicates. Demo designation
alone does not independently prove records are synthetic. Forecast scale and
representative/vulnerable-person safeguards remain to be approved.

Verified live controls include public HTTPS with valid certificate checks,
HSTS, secure session/CSRF cookies, nosniff and framing denial; PostgreSQL TLS 1.3;
debug disabled; a valid clinical-object AES-256-GCM keyring; and a mode-0600
production environment file. Database `sslmode=require` does not require hostname
verification. No stored clinical-document or patient-identifier rows existed, so
there is no existing-record migration/readback or restore result to claim.

All national-provider records are REQUESTED, the DHA tables are empty, and the
inspected RX/checkout configurations have no enabled flags. This covers these
specific activation paths; actual outbound email, logs, exports, support access,
legacy provider settings and other disclosures still need a full inventory.

## Confirmed gaps and evidence limits

| Area | Finding | Required closure |
|---|---|---|
| Hosting | VPS metadata is `nbg1-dc3` / `eu-central`. Hetzner maps it to Nuremberg, Germany; database target and clinical objects are on that VPS. Owner confirmed Kenya hosting needs arranging. | Kenya deployment/serving-copy and legal transfer/localization assessment; see [acceptance plan](22_KENYA_HOSTING_ACCEPTANCE_PLAN.md). |
| Retention | Seven years is owner direction; start events, minors/exceptions, holds, backup expiry and return/deletion lifecycle remain unspecified and unproven. | Signed class schedule, implementation and synthetic hold/purge/offboarding/restore tests. |
| Privileged access | No in-application privileged MFA implementation was identified in the reviewed release. External compensating control and recurring access review are not evidenced. | MFA enrolment/challenge/recovery/revocation and review, or a specifically assessed temporary restriction/control with owner/expiry. |
| Key lifecycle/at rest | Object keyring valid; identifier crypto still derives from Django SECRET_KEY. No local dm-crypt devices observed; ext4 is not encryption proof. Provider-level host/DB encryption unverified. | Versioned independent identifier keys; DB/object/backup at-rest and separate key-custody evidence; tested rotation and restore. Do not blindly replace SECRET_KEY. |
| Malware | Required scanning is disabled and scanner endpoint absent. New deferred uploads are NOT_SCANNED; no active ClamAV test performed. | Activate private scanner and require CLEAN, or bound/restrict uploads through a reviewed exception with explicit residual risk. Prior user deferral remains in force; this review did not change it. |
| Backups/recovery | Encrypted release archives have checksum/decryption/inventory evidence, but keys and archives share the VPS. Those manifests explicitly say not a restore rehearsal. | Separate protected copy/key custody, coordinated schedule, approved retention/RPO/RTO and full restore-exercise record. Owner says one exists; link and verify it. |
| DHA and independent assurance | Owner declares DHA Certified, security assessment Passed and restore evidence available; matching DHA/security/restore report references were not supplied or found. | Attach issuer certificate/scope/expiry/version, assessor report/retest, and measured DB/object restore report. Do not treat missing attachment as proof the declaration is false. |
| Governance | Purpose/role/basis or controller instructions, contracts, support countries, transparency/rights route, consultation and residual-risk decision incomplete. | Review signed records against actual flows and the applicable legal requirements; record approvers and dates. |

## Provisional risk scoring

Impact and likelihood each range 1 (lowest) to 5 (highest). Score is the sum,
following the calculation shown in the General Regulations' Third Schedule.
Internal review bands are 2-4 low, 5-7 medium and 8-10 high; these are not statutory
approval thresholds. Scores are professional review judgments for validation by
the owner/DPO, not measured probabilities or accepted residual risk.

| Risk | Initial impact + likelihood | Current residual impact + likelihood | Current treatment |
|---|---|---|---|
| Cross-tenant or excessive access | 5 + 4 = 9 | 5 + 3 = 8, High | Tested tenant/capability controls; independent assessment and recurring access review open |
| Privileged account/device compromise | 5 + 4 = 9 | 5 + 3 = 8, High | Password/session controls; privileged MFA/device assurance open |
| Hosting/localization or transfer failure | 5 + 4 = 9 | 5 + 4 = 9, High | Actual location identified; Kenya serving deployment/legal review outstanding |
| Keys, database or object compromise | 5 + 4 = 9 | 5 + 3 = 8, High | TLS/object keyring/encrypted archives; at-rest/key custody/identifier lifecycle open |
| Malicious upload | 4 + 4 = 8 | 4 + 4 = 8, High | Truthful NOT_SCANNED state; required clean scanning deferred |
| Excessive retention or premature disposal | 5 + 4 = 9 | 5 + 4 = 9, High | Seven-year direction only; triggers/holds/lifecycle open |
| Unrecoverable outage/data loss | 5 + 4 = 9 | 5 + 3 = 8, High | Release backup evidence; separate copy and full measured restore open |
| Clinical inaccuracy/improper authority | 5 + 4 = 9 | 5 + 3 = 8, High | Human/provenance safeguards and CI; clinical/source/representative assurance open |
| Undetected breach or undisclosed secondary use | 5 + 4 = 9 | 5 + 3 = 8, High | Application audit/draft policies; external audit, incident exercise and purpose inventory open |

The small demo-patient population does not remove risks to actual workforce
accounts or foreseeable production health processing. Reassess scores after
remediation and define the scale for which the decision is valid. No high residual
risk is accepted here; resolve or obtain the appropriate lawful risk decision and
consultation before approval.

## Restricted evidence packet and reproducibility

Packet location, relative to repository root:
`artifacts/generated/compliance/dpia-2026-10-25/` (git ignored, directory 0700,
files 0600). Do not add this folder to the public repository or publish it.

| Evidence | What it establishes |
|---|---|
| OWNER_DECLARATIONS.json | Direct owner statements, contacts and later hosting correction; not signatures |
| ODPC_PROCESSOR_CERTIFICATE.pdf / ODPC_CERTIFICATE_REVIEW.json | Matching local processor certificate and visual review/hash |
| INCORPORATION_CERTIFICATE.pdf / INCORPORATION_REVIEW.json | Matching company registration document and visual review/hash |
| HOST_EVIDENCE.json | Selected runtime labels/digests, provider region metadata, filesystem indicators, backup-manifest descriptions and TLS headers |
| RUNTIME_EVIDENCE.json / COLLECTOR_RESULT.json | Aggregate read-only results and observed scan gap; automatic fail-on-gaps exited 2 |
| RELEASE_EVIDENCE/ / CI_RUN.json | Exact-source release manifest, checksums, SBOMs, scans, migration evidence and all-job conclusion |
| BACKEND_ATTESTATION_VERIFIED.json / HQ_ATTESTATION_VERIFIED.json | Successful source-ref/source-digest provenance verification |
| EVIDENCE_MANIFEST.json | Packet inventory, hashes and provenance/limitations; integrity inventory is not an external signature |

Collector: [collect_dpia_runtime_evidence.py](../../../scripts/collect_dpia_runtime_evidence.py).
Execute from a trusted backend runtime with PostgreSQL, with stdout redirected to
restricted storage:

```sh
python /trusted/path/collect_dpia_runtime_evidence.py --verify-objects --fail-on-gaps > /restricted/path/runtime.json
```

Exit 2 means measured control failures. Exit 0 means no failure in the collector's
limited automatic checks; it never means the DPIA is approved. Manual governance,
legal, native-device and independent-assurance gates require separate evidence.
Object verification reads/decrypts in memory, emits counts and does not rewrite
objects. The collector is checked against the current model/crypto implementation;
review it when those contracts change. It is a local audit utility, not deployed
application code or a user-facing compliance score.

## Conditions for an approval decision

Close the [register](20_DPIA_GAP_CLOSURE_REGISTER.md), then obtain a dated decision
from the owner and necessary reviewers covering scope, evidence, residual risks,
conditions and review triggers. Attach any Data Commissioner submission/response
or consultation record required for this case. No submission receipt/date was
supplied, so no deemed approval is inferred from elapsed time.

Official sources reviewed: [General Regulations](https://www.odpc.go.ke/wp-content/uploads/2024/03/THE-DATA-PROTECTION-GENERAL-REGULATIONS-2021-1.pdf),
especially regulations 19, 26, 49-53 and Third Schedule;
[DHA certification evidence requirements](https://certification.dha.go.ke/);
[Hetzner region mapping](https://docs.hetzner.com/cloud/general/locations/).
The scanned ODPC guidance PDF was not fully retrievable in this review.
