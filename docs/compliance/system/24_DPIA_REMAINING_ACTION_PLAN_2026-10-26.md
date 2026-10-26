# TibaTrace DPIA and DHA remaining action plan

**Updated:** 26 October 2026<br>
**Decision:** DPIA remains **NOT APPROVED**; this plan does not grant regulatory approval or certification.<br>
**Production boundary:** server release `1.0.0-rc71`, commit `2965194a29311314e8a5772adfeee5af8c14a8f2`, Hetzner Nuremberg, Germany.<br>
**Unshipped source:** local commit `f8ea5cd` adds versioned patient-identifier keys and FHIR intake safeguards. It is not deployed and is not production evidence.

This is the working checklist for the documents in this folder. Findings and closure tests remain in the [DPIA gap closure register](20_DPIA_GAP_CLOSURE_REGISTER.md); the evidence boundary and risk decision remain in the [DPIA](01_DATA_PROTECTION_IMPACT_ASSESSMENT.md) and [25 October review](21_DPIA_CURRENT_REVIEW_2026-10-25.md). A declaration or code change closes a row only after the specified evidence is checked.

## What is already prepared

The repository contains the system DPIA, privacy notice, system architecture, user manual, technical specification, security and incident policies, encryption and audit specifications, backup and disaster-recovery plans, public-health/terminology specifications, access and retention policies, security assessment status reports, evidence checklist, gap register, current review, Kenya hosting acceptance plan, identifier-key rollout guide, this action plan, and a DHA evidence register, classification, requirements catalogue, traceability matrix, scorecard, test plan, demonstration script, and change-governance draft.

These are **review-ready working documents, not a complete approved submission**. Current status:

| Workstream | Status now | What completes it |
|---|---|---|
| System DPIA | Draft, NOT APPROVED | Verified processing facts, risk treatment, consultation, signed decision and any required ODPC prior consultation |
| Corporate/ODPC identity | Partly evidenced in restricted packet | Verify certificate scope/status with issuer; confirm current registered address, DPO appointment/contact route and provider roles |
| DHA status | Owner says “Certified”; not verified in reviewed evidence | Certificate number/copy, system and release scope, dates, conditions and facility go-live proof, checked against DHA records |
| Production hosting | Germany is verified; Kenya capacity is not arranged | Legal applicability decision and executed/verified Kenya server or serving-copy design, provider terms and data-flow evidence |
| Retention | Owner's seven-year baseline recorded | Approved record-class start events/exceptions/holds and tested retention/deletion lifecycle |
| Security assessment | Owner says Passed; report not located | Signed independent report, tested version/scope, findings and retest evidence |
| Recovery | Owner says exercise exists; report not located | Full database + clinical-object + key restore report, measured RPO/RTO, recurring schedule and separate failure domain |
| Identifier keys | Source change in local `f8ea5cd`; not deployed | Independent review, production key provisioning, safe rollout/migration, readback/restore and exact release verification |
| Malware scanning | Deliberately deferred; no scanner endpoint configured | Activate and verify ClamAV or another approved scanner; otherwise restrict affected uploads under an approved time-bound exception. Deferred scanning does not support a DPIA pass for those uploads |
| Integrations | DHA/national-provider/RX/checkout activation is off in reviewed production | Tenant-specific purpose, controller approval, credentials, endpoint, contracts, test/conformance and go-live approval before enabling |
| Policies/manuals | Drafts exist | Named owners approve them and operational records demonstrate they are followed |

## Required steps, in order

### 1. Verify the declarations and appoint accountable reviewers

**Owners:** Sidney Chepkwony, privacy lead/DPO, legal reviewer.

1. Match the Esenai Group Ltd incorporation and ODPC Data Processor certificate to the registered entity, role and current service. The processor number supplied is `890-695D-435E`; the certificate copy was visually reviewed in the restricted packet, but issuer verification and other role applicability remain to be recorded.
2. Verify the DPO/privacy lead appointment, monitored address, rights-request route and incident escalation route. Keep the exact contact in the restricted contact register.
3. Obtain the DHA certificate reference/copy the owner says exists. Check issuer, system name, product/version, category, effective/expiry dates, conditions and facility go-live scope. If it does not cover this system/release/use, ask DHA to confirm the next required step; do not treat an application or this local scorecard as certification.
4. Obtain the independent security-assessment report and the full restore-exercise report the owner says exist. Record assessor/provider, date, tested release, environment, exclusions, findings, remediation and retest. If the reports cannot be found, commission/re-run the missing work.

**Close when:** named reviewers and roles are verified, and each declaration is either supported by scoped evidence or explicitly corrected to OPEN.

### 2. Resolve hosting, localization and every data route

**Owners:** infrastructure owner, privacy lead/DPO, legal reviewer.

1. Use [Kenya hosting acceptance plan](22_KENYA_HOSTING_ACCEPTANCE_PLAN.md) to choose the Kenya deployment/serving-copy design, provider and region. The current audited host is Germany; no Kenya copy is evidenced.
2. Have counsel document whether regulation 26 applies to each actual processing purpose. It refers to specified purposes, including primary or secondary healthcare. If applicable, evidence the required Kenya server or at least one Kenya serving copy. Record the legal conclusion and its factual basis even if the chosen architecture differs.
3. Inventory production database, clinical files, backups, logs, support access, email/SMS, payment, tax, insurer, regulator, analytics and monitoring providers. For each, record legal entity, data, purpose, country, access/support countries, contract/DPA, retention and enabled status.
4. Reconcile the privacy notice, DPIA flow diagram, contracts and live configuration to that inventory. Keep unapproved exchanges disabled.

**Close when:** the Kenya plan is executed or the legal reviewer records a supported applicability conclusion, and all actual storage, support and recipient paths match the documented register.

### 3. Complete purpose, role, population and necessity records

**Owners:** product/service owner, privacy lead/DPO, clinical lead, legal reviewer.

1. For each provider purpose, record the provider's controller/processor role, purpose, necessity, categories, recipient, lawful basis and health-data condition or customer instruction. Separately document customer-controller purposes; do not choose a customer's legal basis for it.
2. Provide aggregate current and annual forecast counts for patients, prescriptions, practitioners, workforce and transactions. State source/date/assumptions and whether children or other vulnerable people are included. Do not send patient-level data into the evidence pack.
3. Document necessity and proportionality for identifiers, clinical images/PDFs, access logs, analytics and exports; name the data minimization, correction, rights-request and human-review controls.
4. Update the privacy policy, processing inventory, contracts and DPIA with the verified facts.

**Close when:** the owner, DPO and legal reviewer approve the purpose/role/necessity register, scale envelope, actual data-flow inventory, notices and service/DPA terms.

### 4. Approve a real retention schedule before building deletion rules

**Owners:** system owner, tenant/controller representative as applicable, privacy lead/DPO, legal reviewer.

The seven-year period is an owner-stated baseline only. For each record class—prescription, dispensing, patient identity, payment/tax, stock, audit, staff account, integration message, support record, export, and backup—write down the start event, period, applicable legal/contract basis, exception, legal hold, access restriction, return/deletion action, backup expiry and accountable approver. Set periodic review periods. Resolve conflicts with clinical, tax, accounting and other binding requirements with counsel.

**Do not implement irreversible deletion from “7 years” alone.** Once signed, Engineering maps the approved schedule to primary records, objects, caches, exports, queues and backups; test expiry, holds, customer exit, deletion audit and post-restore reconciliation with synthetic data.

**Close when:** the schedule is signed and its implementation and synthetic lifecycle evidence match it.

### 5. Deploy and verify the source-only identifier remediation safely

**Owners:** release/security engineers, infrastructure owner, independent reviewer.

1. Review [identifier-key rollout](23_IDENTIFIER_KEY_REMEDIATION_AND_ROLLOUT.md) and commit `f8ea5cd`; confirm current branch/source and change set before release.
2. Complete independent code/security review and the normal release gates against the exact source. Prepare tested rollback and a protected backup before changing configuration or schema.
3. Generate/provision the independent encryption and lookup keyrings through the approved secret-management process. Never place real key material in this repository, tickets, logs or chat. Record key IDs, owners, access controls, backup/recovery and rotation policy, not secret values.
4. Deploy to a controlled environment first. Verify legacy decrypt/lookup compatibility, new writes, tenant separation, FHIR intake, index rebuild/rotation, audit events, failure handling and recovery using synthetic records.
5. Promote only after change approval. Record signed artifact digests, migrations, production configuration predicates, smoke/readback results and rollback readiness. Then re-evaluate DPIA-08; do not rewrite the 25 October evidence record.

Also obtain evidence for database/host/object/backup at-rest encryption, separate key custody, least-privilege access and rotation. Application encryption by itself does not prove storage-volume encryption.

**Close when:** the exact released source is deployed, independently reviewed, key operation and recovery are verified, and the production claims match the evidence.

### 6. Close operating security and recovery gaps

**Owners:** security and infrastructure owners.

1. Enable privileged-user MFA with enrolment, challenge, recovery, revocation and tested emergency access; run and retain periodic user/device/leaver reviews.
2. Activate ClamAV or another approved private malware scanner. Test clean, infected, timeout/unavailable, oversize and retry cases. Require a clean verdict before making an attachment available. Until then, disable/restrict affected uploads or use a named, time-limited exception approved by privacy/security; `NOT_SCANNED` is not `CLEAN`.
3. Place backups and key recovery material in a separate failure domain with approved access, retention and monitoring. Verify recurring coordinated backups for database, objects, configuration and keys.
4. Run a witnessed full restore; record dataset/version, integrity checks, measured RPO/RTO, gaps, follow-up and approver. Check whether the owner's claimed exercise meets this scope before treating it as evidence.
5. Commission or attach independent penetration/security assessment mapped to the exact server and client versions. Close findings and retest. Exercise incident response and verify contact/escalation routes.

**Close when:** live configuration and dated operating evidence prove each control, and any remaining risk has an explicit scope, owner, expiry and approval.

### 7. Keep DHA and tenant exchanges governed and disabled until ready

**Owners:** product owner, tenant controller, integration owner, privacy/security reviewers.

For each tenant and each interface, record the intended purpose and fields, legal/contract authority, patient notices/consent where required, recipient and country, provider agreement, tenant-specific credentials, callback/allowlist, test environment, mapping/version, error/retry/dead-letter handling, audit/retention, incident contact and disable/rollback method. Run conformance/sandbox and operational tests, obtain the required DHA/facility/tenant approvals, then activate by a documented change. Keep the integration disabled if any prerequisite is absent. No credentials belong in this plan.

**Close when:** current DHA classification/certificate and applicable facility go-live conditions are verified, each tenant's approval and credentials are validated, and only explicitly approved routes are enabled. The owner statement “DHA Certified” remains unverified in the reviewed evidence until step 1 is complete.

### 8. Consult, submit if required, and sign the final decision

**Owners:** Sidney Chepkwony, privacy lead/DPO, counsel, clinical/security/service representatives.

1. Consult affected internal teams and representative tenant/customer/patient stakeholders as appropriate. Record participant role, date, method, material concern and design/risk response; do not include unnecessary personal details.
2. Re-score each risk after the evidence above is complete. Record any unmitigated risk, owner, treatment, due date and operational restriction. Do not accept a high residual risk by silence.
3. Have counsel determine and document whether prior Data Commissioner consultation is required under section 31 for the final high-risk processing. If required, submit the complete version, keep the receipt/correspondence and follow the authority's decision. Do not infer approval from elapsed time without complete submission and correspondence evidence.
4. Obtain dated sign-off from Esenai's accountable system owner, privacy lead/DPO, clinical lead, security/operations owner and legal reviewer. Update this DPIA version, the register and the document index to the exact evidence/release boundary.

**Close when:** every blocking register item has verifiable evidence or a legally reviewed, approved residual-risk treatment; consultation and any required ODPC process are recorded; and the accountable owner signs the DPIA. Only then may the decision be reconsidered.

## External references for reviewer confirmation

- [Kenya Data Protection Act, 2019, section 31](https://new.kenyalaw.org/akn/ke/act/2019/24/eng@2022-12-31/source)
- [Data Protection (General) Regulations, 2021, including regulations 19, 26 and 49–53](https://www.odpc.go.ke/wp-content/uploads/2024/03/THE-DATA-PROTECTION-GENERAL-REGULATIONS-2021-1.pdf)
- [ODPC DPIA guidance](https://www.odpc.go.ke/wp-content/uploads/2024/02/ODPC-Guidance-Note-on-Data-Protection-Impact-Assessment-1.pdf)
- [DHA certification guidance and current workflow](https://certification.dha.go.ke/regulatory-guide)
- [DHA system categories](https://certification.dha.go.ke/systems)

This checklist organizes evidence and engineering work. It is not legal advice, a regulator submission, an ODPC decision, or a DHA certificate.
