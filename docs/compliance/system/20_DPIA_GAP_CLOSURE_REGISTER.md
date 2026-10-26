# TibaTrace System DPIA Gap Closure Register

**Assessment:** TibaTrace system/provider DPIA, version 0.4<br>
**Evidence review:** 25 October assessment plus rc74 deployment acceptance on 26 October 2026<br>
**Status:** OPEN — the assessment remains not approved<br>
**Purpose:** Track the facts, controls, and accountable decisions needed to close the DPIA findings. This register is not a certificate, legal opinion, or approval.

## Current disposition

The [current review](21_DPIA_CURRENT_REVIEW_2026-10-25.md) supersedes the old
rc52/rc57 evidence boundary. The matching incorporation and ODPC processor
certificates were visually reviewed; the privacy contact and approval owner are
recorded. rc71 server identity, CI/scans/provenance, TLS, clinical-object keyring,
aggregate current scale and selected inactive integration paths are verified.
Certificate copies, contacts, counts and operational reports are retained in the
restricted, git-ignored packet described in that review.

The audited VPS is in Germany. The owner confirmed Kenya hosting needs arranging.
Seven years remains a baseline without approved class triggers. DHA certification,
a passed independent security assessment and a restore exercise are owner-declared;
the matching reports/certificate references have not been attached. These facts do
not permit the DPIA to be marked approved.

**26 October deployment update:** Independent versioned identifier keys and protected FHIR paths are deployed in rc74. [Acceptance](../../releases/RC74_DEPLOYMENT_2026-10-26.md) verifies release identity, key provisioning, additive migration, tenant preflights, rolled-back synthetic readback and encrypted configuration recovery. No stored identifiers required rotation. DPIA-08 remains PARTIAL for independent review, storage encryption/custody, rotation lifecycle and full recovery; the historical rc71 assessment remains preserved.

**Further engineering work, 26 October:** New MFA, native OTP inputs, governed
recovery/rotation, restricted access-review export, signed audit checkpoints,
authenticated backup tooling and a synthetic PostgreSQL recovery rehearsal are
tested, including 2,546 PostgreSQL 16 business tests and synthetic coordinated
recovery. These changes are not deployed. See
[technical delivery](25_TECHNICAL_DPIA_CONTROL_DELIVERY_2026-10-26.md) and the
[exact owner evidence checklist](26_OWNER_EVIDENCE_AND_APPROVALS_REQUIRED.md).
Scanning remains deferred and integrations remain disabled. Live enrollment,
independent review, separate custody and operational approval remain open.

## Closure items

| ID | Priority / current state | Finding and current evidence | Accountable owner | Closure test |
|---|---|---|---|---|
| DPIA-01 | Blocking / PARTIAL | Incorporation and matching ODPC Data Processor certificate visually reviewed; contact and approval owner supplied. Current address, issuer verification, controller-role applicability, named reviewers/appointment and signed role analysis still needed. | Sidney Chepkwony / privacy lead | Attach current entity/contact/role records, verify issuer/scope as appropriate, name reviewers and record dated approvals. |
| DPIA-02 | Blocking / OPEN | Provider purposes, role-specific basis or controller instructions, notices and service/DPA terms not yet approved against actual flows. Processor registration does not determine every purpose. | Service owner / privacy lead / legal reviewer | Approve the purpose/field/necessity/role/basis-or-instruction register, notice, confidentiality and DPA; verify rights/support routes. |
| DPIA-03 | Blocking / PARTIAL | Server rc74 labels/digests, all-job CI, exact-source coverage, image scans and provenance verified in the 26 October acceptance. Native installers/devices and broader operating assurance are outside this check. | Release / security owner | Retain current server evidence; attach native client identity/storage/signing and endpoint/tenant assurance for the full assessment scope. |
| DPIA-04 | Blocking / PARTIAL | Aggregate current scale, demo separation, age bands and privileged account counts captured without record export. Forecast capacity, non-demo growth and vulnerable-group assumptions remain open. | Product / service owner | Approve forecast/scale envelope, source/date/assumptions and representative safeguards; do not treat demo designation as independently verified synthetic provenance. |
| DPIA-05 | Blocking / CONFIRMED HOSTING GAP | Live region nbg1-dc3/eu-central is Nuremberg, Germany. Owner corrected initial Kenya declaration: Kenya hosting needs arranging. DB target/clinical objects share VPS. Selected national/DHA/RX/checkout paths inactive; complete recipients/support/subprocessors still need inventory. | Service owner / infrastructure / privacy/legal | Execute [Kenya acceptance plan](22_KENYA_HOSTING_ACCEPTANCE_PLAN.md); evidence actual Kenya serving/storage, contracts/support countries and any lawful foreign-copy/transfer safeguards. |
| DPIA-06 | Blocking / OPEN | Owner reaffirmed seven years, but class start events, minors/clinical/accounting exceptions, legal holds, service exit and backup expiry are unspecified. | System owner / privacy lead / legal reviewer | Sign completed class schedule in retention policy before mapping irreversible disposal rules. |
| DPIA-07 | Blocking / OPEN | End-to-end retention/hold/return/deletion and post-restore reconciliation remain unimplemented or unproven in assessed scope. | Engineering / operations | Implement approved schedule and test expiry, hold, offboarding, objects/exports/cache, backup expiry and restore reconciliation with synthetic records; preserve disposition audit. |
| DPIA-08 | High / PARTIAL | rc74 independent identifier keyrings, object keyring, encrypted pre/post archives, synthetic key/FHIR acceptance and configuration recovery readback verified. No stored identifiers required rotation. Independent review, provider/database at-rest protection, separate custody, ongoing rotation and full recovery remain open. | Security / infrastructure | Follow [identifier key rollout](23_IDENTIFIER_KEY_REMEDIATION_AND_ROLLOUT.md): provision keys separately, deploy exact reviewed source, migrate/reindex safely, verify synthetic round-trip and backup restore, then evidence at-rest layers/custody and rotation. Do not blindly rotate `SECRET_KEY`. |
| DPIA-09 | High / OPEN | Password/session and role controls present. rc74 has no enforced privileged MFA. New enrollment/session/JWT/recovery and review-export code passed engineering tests; no live enrollment/enforcement or recurring access-review evidence. | Identity / security owner | Implement and verify MFA enrolment/challenge/recovery/revocation; account/device/leaver review; document any lawful temporary exception with scope/owner/expiry. |
| DPIA-10 | High / CONFIRMED SCANNER GAP | Malware scanning explicitly deferred; required-scan flag false, endpoint absent. New deferred uploads are NOT_SCANNED. Owner says assessment Passed but independent report absent. Audit delivery/protection and incident operation unproven. | Security / operations | Activate/test scanner clean/infected/unavailable paths or bound uploads through a reviewed exception; attach independent assessment/retest, protected audit and incident exercise. Previous scan deferral was not reversed by this audit. |
| DPIA-11 | High / PARTIAL | Encrypted release backups verified; inspected manifests explicitly exclude a full restore rehearsal. Keys/archives share VPS. Owner says separate exercise exists; no report reference supplied. Selected cron/timer checks did not establish a coordinated TibaTrace schedule, but are not an exhaustive scheduler audit. | Infrastructure / service owner | Attach/verify separate exercise, DB+object+key restore, measured RPO/RTO, recurring coordinated schedule, retention, off-host copy and separate key custody. |
| DPIA-12 | Blocking evidence gate / OWNER-DECLARED | Owner states DHA Certified. No matching issuer certificate/reference/scope was provided or found in reviewed material. Selected DHA paths remain inactive. | Product / legal reviewer | Attach and verify DHA certificate/date/expiry/version/conditions and applicable facility go-live scope. Missing attachment is not proof the declaration is false. |
| DPIA-13 | Blocking / OPEN | Owner answers/clarification recorded; full stakeholder consultation, signed residual-risk decision and any Data Commissioner submission/consultation evidence missing. | Sidney Chepkwony / privacy lead / legal reviewer | Complete consultation and signed scope/risk decision after mitigation; attach submission receipt/outcome or documented legal applicability decision. Do not infer deemed approval without complete submission/correspondence evidence. |

## Safe execution order

1. Resolve DPIA-05 Kenya hosting/localization/transfer gap while completing the remaining owner/role/contract, native-client and forecast evidence in DPIA-01 through DPIA-04.
2. Approve DPIA-06 before engineering implements irreversible deletion rules. Do not auto-delete health or financial records based on an unspecified seven-year trigger.
3. Close the security and recovery evidence in DPIA-08 through DPIA-11 on the exact production release. Implement a missing control before recording it as complete.
4. Close DHA applicability/certification in DPIA-12 before any legally restricted clinical use or exchange.
5. Complete consultation and residual-risk approval in DPIA-13 after mitigations are evidenced.

For task order, owners, artifacts and the exact closure sequence, use the [26 October remaining action plan](24_DPIA_REMAINING_ACTION_PLAN_2026-10-26.md). This register remains the finding-level source; completing local code or documentation alone does not approve the DPIA.

The assessment can be submitted for review after these items have owners and evidence; only the accountable system owner and required reviewers can change its approval decision. Do not change the status to approved solely because this register or a code test is complete.
