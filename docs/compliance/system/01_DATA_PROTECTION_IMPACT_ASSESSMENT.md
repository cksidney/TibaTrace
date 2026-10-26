# TibaTrace Data Protection Impact Assessment

**Decision:** NOT APPROVED — verified control gaps and accountable review remain outstanding<br>
**Version:** 0.4 (review of the deployed system)<br>
**Assessment date:** 25 October 2026 (Africa/Nairobi)<br>
**25 October assessment basis (historical):** deployed `1.0.0-rc71`, commit `2965194a29311314e8a5772adfeee5af8c14a8f2`. Live API, worker, scheduler and HQ labels match the release. Full CI, SQLite/PostgreSQL coverage, image scans, release checksums and signed image provenance were verified. Read-only production control and aggregate-scale evidence is held in a restricted local packet; see the [current review](21_DPIA_CURRENT_REVIEW_2026-10-25.md). Native POS binaries and individual devices were not re-assessed.<br>
**Assessment owner:** Esenai Group Ltd; Sidney Chepkwony is the owner-nominated approval owner. Nomination is not approval or a signature.

**26 October deployment addendum:** release rc74, `27469e1993d85606001787fb058052fe1cb6b4b6`, is deployed and verified. Independent identifier encryption/lookup keyrings, the additive migration, tenant preflights, rolled-back synthetic key/FHIR checks and encrypted configuration readback passed. See [rc74 acceptance](../../releases/RC74_DEPLOYMENT_2026-10-26.md). The 25 October rc71 snapshot remains historical evidence. DPIA-08 stays PARTIAL for independent review, storage encryption/custody, rotation lifecycle and full isolated recovery. The system DPIA remains NOT APPROVED; owner-declared DHA/security/restore claims still need scoped evidence.

## 1. Decision and scope

TibaTrace is designed to process sensitive health information and identifiable clinical, practitioner, payment, stock, and workforce records. Its nature and context meet the high-risk indicators in section 31 of the Data Protection Act and regulation 49 of the Data Protection (General) Regulations, including sensitive health data, potentially vulnerable people and children, large-scale use as tenants grow, and linking clinical and operational records. A DPIA must be completed before the relevant high-risk processing begins and before any materially higher-risk purpose or exchange is activated.

Because the service is already deployed, this is also a remedial system assessment; it does not retrospectively cure any assessment or approval that should have preceded existing processing. The system owner and counsel must review existing use against the applicable requirements.

This assessment is for **TibaTrace as a digital health product and the service-provider processing it performs**. It covers the product design and provider-operated service, including foreseeable patient, practitioner, workforce, operational and security data. It is not an individual customer/tenant's processing assessment and does not make tenant-specific clinical-purpose or lawful-basis decisions. Separate tenant DPIAs may still be required for a controller's own purposes, but tenant sign-off is not the approval basis for this system assessment. See the [TibaTrace system DPIA evidence checklist](19_TIBATRACE_SYSTEM_DPIA_EVIDENCE_CHECKLIST.md) for product-owner evidence still to collect.

The system owner states that TibaTrace is operated in accordance with applicable law and has provided a seven-year retention baseline. This assessment records those as owner representations; it still tests them against documented purposes, record classes, implementation evidence and legal review. “Within the law” is not a substitute for recording the provider's purpose-specific role and lawful basis or customer instructions. Unknown system-owner facts below are blockers, not assumptions. The prioritized closure tests and owners are tracked in the [DPIA gap closure register](20_DPIA_GAP_CLOSURE_REGISTER.md).

The current evidence replaces the prior rc52/rc57 boundary. Runtime metadata identifies the audited VPS as Hetzner `nbg1-dc3`, `eu-central`, mapped by the provider to Nuremberg, Germany. The owner initially declared Kenya hosting, then confirmed Kenya hosting needs arranging. No Kenya serving copy is evidenced. Resolve this discrepancy and applicable localization/transfer requirements using the [Kenya hosting acceptance plan](22_KENYA_HOSTING_ACCEPTANCE_PLAN.md). Aggregate current scale and selected controls are now measured; forecast scale, contracts and independent assurance remain open.

**Interim decision:** keep the DPIA marked not approved until the controls and evidence in Section 7 are complete and the accountable owner records a residual-risk decision. The owner declares DHA certification, a passed security assessment and an existing restore exercise; matching reports/certificate references have not been attached. These declarations are recorded without treating them as independently verified. DHA exchange remains inactive.

## 2. Processing operation and parties

| Field | System-level finding | Required system-owner confirmation |
|---|---|---|
| Project | TibaTrace, a multi-tenant pharmacy/healthcare operations platform with HQ web, Windows and Android POS, Django API, PostgreSQL, Redis/Celery, and clinical-document storage; hosted release rc71 verified | Complete native-client/device evidence and forecast scope |
| System owner/provider | Esenai Group Ltd; local incorporation certificate `PVT-LRUX9R6`, dated 8 November 2020, visually reviewed. Matching ODPC Data Processor certificate `890-695D-435E`, serial 31078, valid 15 October 2026 to 15 October 2028, visually reviewed and archived privately | Confirm current registered address, issuer verification, role-specific controller-registration applicability and signed contracts; processor registration is not DPIA approval |
| Processing role | For customer patient/facility data, the provider is intended to process data on the relevant health controller's instructions where contracts and actual operations support that role. The provider may be controller for its own workforce, account, billing, service-security and product operations | Confirm role per provider purpose, current service/DPA terms, instructions and whether any independent purpose exists |
| Other parties | Hetzner region and same-VPS database/object location observed; inspected DHA/RX/checkout activation paths inactive | Complete legal hosting entity/DPA, support countries, all recipient paths, Kenya serving deployment and transfer/localization assessment |
| System DPO/privacy lead | Owner supplied a DPO contact; exact contact retained in restricted owner declaration | Verify appointment/responsibility and operational rights/incident route |
| Approval owner | Sidney Chepkwony, nominated by owner | Dated review and signature after remediation; no acceptance of current residual risks recorded |

Provider/controller/processor roles must be assessed per purpose from actual decisions, contracts and operations, not inferred only from product labels.

## 3. Description of processing and information flow

### 3.1 Data subjects and categories

Data types depend on modules enabled and tenant practice. The design can process:

| Data-subject group | Personal data potentially processed | Sensitivity / special consideration |
|---|---|---|
| Patients and pharmacy clients | Demographics and contact details; identifiers; health conditions, allergies, prescriptions, dispensing and encounter records; clinical attachments; service and payment references | Health data is sensitive personal data. Children and people needing a representative may be included; confirm age bands, guardianship and relevant safeguards |
| Practitioners and prescribers | Identity, professional role, licence/authority claims and verification evidence, facility association, clinical actions | Professional information and attributable clinical activity; establish the authoritative source and correction route |
| Tenant workforce and users | Name/contact, account identifier, role/capability, authentication/session events, device identifiers, access and audit events | Employment and security information; restrict monitoring to stated accountability/security purposes |
| Customers, suppliers, insurers and business contacts | Contact/account details, sale, claim, stock, invoice, payment and refund references | Financial/transaction information; identify when linked transactions reveal patient care or health status |

This system assessment covers foreseeable multi-tenant scale. The restricted runtime packet now contains aggregate current counts, demo-tenant separation and recorded age bands. All current patient rows belong to the designated demo tenant; designation alone does not independently prove every row is synthetic. Account/workforce data still requires protection. No patient-level export was made. Forecast capacity, growth assumptions and vulnerable-population safeguards remain owner evidence requirements.

### 3.2 As-designed flow and boundaries

1. Health providers, pharmacists and authorized customer personnel enter or update data in HQ/POS; patients or representatives may provide details and prescriptions. Imported data and external source data must be identified and provenance preserved by the relevant workflow.
2. HQ/POS sends requests over the configured HTTPS edge. The API authenticates the actor, resolves tenant context, applies capability checks and tenant-scoped access, then reads/writes the shared-schema PostgreSQL system of record.
3. Redis supports cache and queued work and is not the system of record. Celery workers process tenant-scoped background tasks. Clinical attachments use a local object volume. New objects use AES-256-GCM with tenant/object-bound context; downloads require authorization and integrity checks. A valid production keyring is now verified, but no clinical documents or patient identifier rows existed in the snapshot, so legacy migration/readback and rotation/restore cannot be claimed. Database TLS 1.3 is active with `sslmode=require`; hostname verification is not required by this setting. Host/database encryption at rest remains unproven. Malware scanning is explicitly deferred and no scanner endpoint is configured.
4. Authorized users may use in-product views and reports. Exports, printed records, customer messaging, analytics, support access and manual disclosures are additional system flows; the product owner must document the controls and contracted responsibilities for them.
5. External payment, insurer, regulator, terminology, surveillance or health-information-exchange endpoints are separate trust boundaries. Templates or FHIR routes do not prove a live connection. The system owner must inventory production configuration and traffic. Before activation, document recipient, purpose, minimum fields, lawful authority, country, contract/data-sharing agreement, safeguards, testing and approval.
6. Data deletion/return must follow the approved seven-year baseline, a defined start trigger per record class, legal holds and service exit terms. The reviewed materials do not prove an automated end-to-end deletion lifecycle spanning primary records, attachments, exports, replicas, backups and restoration.

### 3.3 Storage, location, and retention

The observed hosted shape uses a Germany VPS, Caddy, application containers, PostgreSQL, Redis, and a clinical-object volume. The protected environment file has mode 0600. Encrypted release backup archives and their keys are on that same host; inspected manifests verify archives but expressly do not claim a full restore rehearsal. The owner says a separate restore exercise exists; attach that report. The host filesystem is ext4 and no local dm-crypt device was observed; this does not independently establish whether the provider encrypts underlying infrastructure. Kenya hosting, contracts, support access countries, a separately protected copy, key custody and full subprocessor inventory remain open.

The system owner has stated a **seven-year retention baseline**. The start trigger, covered record classes, exceptions and interaction with legal holds have not yet been specified in approved policy evidence. The reviewed retention policy remains a draft and does not prove a configurable lifecycle purge or completed service-exit purge. The system owner must map seven years to each system record class and prove deletion/return for primary records, attachments, exports, replicas, backups and restoration. Until then, storage limitation and erasure remain high residual risks.

## 4. Need, necessity, proportionality, and lawful basis

The high-risk nature of health processing warrants the assessment; it does not make every field or use necessary. TibaTrace must provide configuration and role controls that limit fields and access to documented purposes. The product owner represents that its processing is lawful; the system provider's own purposes and corresponding bases must be supported by its privacy notice, records of processing and service terms. A customer controller remains responsible for choosing the lawful basis for its own patient-care purposes. The ODPC health-data guidance distinguishes consent to receive a health service from consent as a data-protection lawful basis.

| Purpose | Minimum data needed to support the product purpose | Product/design safeguard | System-provider conclusion and customer boundary |
|---|---|---|---|
| Patient identification and safe care/dispensing | Only identifiers, prescription, allergy, medication and encounter details needed to support the configured provider workflow | Mask identifiers by default; reveal only by authorized, audited action; avoid unnecessary free text and duplicate identity collection | TibaTrace provides a processor workflow under documented customer instructions. The care provider/controller selects and records its lawful basis and health-data condition; TibaTrace must not activate the purpose without that instruction and role authorization. |
| Pharmacy stock, sale, refund and financial reconciliation | Product, batch, quantity, price, tender/refund references and only the patient/customer linkage required for the transaction | Separate payment credentials from clinical data; minimize patient linkage and staff access | TibaTrace supports distinct operational workflows; the applicable controller determines the purpose and any statutory basis. The system owner documents its own billing/payment processing separately. |
| Practitioner and user identity/access | Account, role, professional authority, device and security events needed for access and accountability | Individual accounts; least privilege; expiry/revocation and periodic review; avoid unrelated workforce data | Assign provider vs customer-controller responsibility per data item and service contract; document the system owner's own workforce processing basis in its processing record. |
| Security, support, audit and service operation | Minimal account/device/request metadata, audit events, error data and support evidence | Tenant-scoped access; redact health payloads; use named support access and record it; segregate service telemetry from clinical content | Record which activities are performed under customer instruction and which are TibaTrace's own security/service operations; document the provider basis, retention and support access. |
| Statutory reporting, claims or external exchange (conditional) | Only fields mandated by a verified recipient/profile and authorized use case | Keep disabled until data-sharing authority, agreement, minimization, accuracy and end-to-end testing are approved | TibaTrace must identify the recipient, purpose, country, legal authority, contract and safeguards before enabling the interface; customer-specific legal bases remain outside this product assessment. |

The system owner represents that TibaTrace operates within applicable law. For this system assessment, the owner must distinguish processing performed on customer instructions from TibaTrace's own controller purposes and record its own lawful bases and notices. TibaTrace must support customers' documented instructions and must not claim to decide their care-purpose lawful bases. Where health data is processed, the responsible health provider or other legally permitted actor and applicable condition must be documented. Consent should not be assumed where another lawful basis applies; when used, it must be valid for the stated purpose.

## 5. Data protection principles and safeguards

| Principle | Evidence in the reviewed design/source | Remaining product-owner evidence |
|---|---|---|
| Lawfulness, fairness and transparency | Capability checks, masked identity views, draft notice and audit patterns; incorporation/processor certificate visually reviewed; privacy contact supplied | Purpose-specific role/basis or customer instructions, approved notice, rights-route verification and any additional registration applicability |
| Purpose limitation | Provider templates require explicit activation; this review found no evidence that templates alone transmit data | Verify production integrations and disable unknown routes; the system owner must record each recipient, purpose, agreement and fields |
| Data minimisation | Sensitive identifiers are masked in ordinary views; role/capability separation is documented | Product owner must complete field-to-purpose inventory; validate reports, exports, search, logs and third-party payloads |
| Accuracy | Domain workflows and provenance requirements are documented for selected clinical/terminology information | System owner must document source provenance, correction capabilities and controls for duplicate/incorrect data; customer clinical source-of-truth duties remain outside this product assessment |
| Storage limitation | User-provided seven-year baseline is recorded; draft retention/disposal policy defines lifecycle requirements | Approve record-class triggers/exceptions and implement/test primary/object/export/backup lifecycle and legal holds |
| Integrity and confidentiality | Exact-source rc71 suite passed; live HTTPS/security headers, database TLS 1.3 and object keyring verified. Identifier/object authorization and encryption are implemented; no stored documents/identifiers existed in the snapshot | Host/database encryption at rest, separate key custody, rotation/full recovery, active scanner, privileged MFA, access reviews, independent testing and protected audit delivery remain open. rc74 identifier-key deployment and synthetic readback are verified in the deployment addendum. Scanning is currently deferred, so source fail-closed behavior is conditional on configuration |
| Accountability | Audit models, change/release records and a system document register exist | Name system owners; produce current access, incident, backup/restore, training, DPIA review, provider/subprocessor and disposal evidence; obtain system-owner/legal approval |

Historical 17 October source tests remain historical evidence. The 25 October release evidence is CI run [40169584453](https://github.com/cksidney/TibaTrace/actions/runs/40169584453), verified against the deployed commit and both image digests. The new aggregate evidence collector passed targeted privacy/read-only/integrity tests and was executed under a PostgreSQL read-only transaction. These checks do not replace independent VAPT, native-device testing, a full restore or accountable approval.

## 6. Risk assessment

The scenario table describes potential impact and incomplete treatments. Provisional impact/likelihood scores and their method are in the [current review](21_DPIA_CURRENT_REVIEW_2026-10-25.md). High residual risk is not accepted by this assessment. The owner and privacy lead must validate the scores against actual scope, safeguards and consultation.

| Risk scenario | Potential impact on rights/freedoms | Existing safeguards evidenced | Gap / required treatment | Residual status |
|---|---|---|---|---|
| Cross-tenant access or over-privileged user | Confidentiality breach, stigma, discrimination, loss of trust, altered care | Tenant/capability controls and exact-source rc71 CI verified | Independent adversarial assessment, recurring access review, denial monitoring and native-device evidence | High until remaining assurance and operating evidence supplied |
| Compromised privileged/staff identity or device | Broad disclosure, fraudulent dispensing or untraceable changes | Strong password validation, sign-in/reset throttling, roles/capabilities, token revocation checks, Windows DPAPI and Android Keystore are documented/tested | HQ privileged MFA is not evidenced; verify MFA or an approved time-limited compensating control, leaver/lost-device revocation, and periodic review on the live deployment | High until control and operational evidence supplied |
| Identifier or attachment/key compromise | Patient re-identification, disclosure or loss of matching/access | Application identifier protection, AES-256-GCM objects, live valid object keyring, authorized downloads and encrypted release backups. rc74 deploys versioned independent identifier keys with synthetic key/FHIR acceptance | No production identifier population to prove migration/readback. Host/database at-rest proof, separate key custody and rotation/restore remain open | High; key/storage controls need closure |
| Malicious clinical upload | Malware, disclosure or service disruption | ClamAV adapter and truthful NOT_SCANNED state; no stored clinical documents at audit | Scanning is deferred and no endpoint is configured. Activate and test clean/infected/unavailable cases, or document a bounded upload restriction/exception accepted by privacy/security | High; scanner deferral remains open |
| Excessive or insufficient retention/deletion | Intrusion on privacy or loss of clinical/financial evidence | Seven-year baseline stated by system owner; draft schedule and disposal requirements exist | No signed class-specific trigger/exception schedule or end-to-end purge is evidenced. Approve the schedule before implementation; then test purge/return across live stores, exports and backups, including restore reconciliation | High; not approved |
| Hosting or recipient localization/transfer failure | Loss of confidentiality, rights impact, unlawful transfer or storage | Live Germany location identified; owner confirms Kenya hosting must be arranged. Inspected national/DHA/RX/checkout configurations inactive | Establish Kenya hosting/serving copy, recipient/support contracts and applicable localization/transfer basis; inventory other disclosures | High; confirmed hosting gap |
| Data inaccuracies or improper clinical use | Wrong medicine, delay, adverse health outcome or misattribution | Audit and selected clinical verification workflows are documented | Establish supported correction/provenance controls and practitioner verification evidence; document customer/source-of-truth responsibilities; validate each clinical module | High for clinical workflows until validated |
| Breach not detected or notified promptly | Prolonged exposure and delayed protection/remedy | Draft incident plan provides response phases and statutory escalation outline | Name responders/DPO and 24/7 contacts; exercise breach/tenant escalation and notification timeline; prove detection coverage | High until operational exercise and contacts exist |
| Service outage, ransomware or unrecoverable data | Interrupted care, lost prescriptions/dispense history, unsafe fallback | Healthy rc71; encrypted release archives with verified inventories | Inspected archives/keys share host; recurring coordinated schedule, separate copy/custody and measured restore proof remain open. Attach the separate exercise the owner declares exists | High until recovery evidence and owner approval |
| Unlawful data use for analytics, model training or surveillance | Unexpected profiling, discrimination, sensitive disclosures | No such use is authorized by this assessment; system specifications state provider templates are not active integrations | Prohibit secondary use absent a separate assessed purpose, lawful basis, transparency, safeguards and authorization; verify actual telemetry and exports | High if any unrecorded secondary use exists |
| Digital-health regulatory evidence incomplete | Inability to demonstrate permitted scope or safe go-live | Owner declares DHA Certified; no certificate/reference attached in this review | Verify certificate, scope, expiry, assessed version and applicable go-live conditions through DHA; keep unapproved exchange inactive | Blocking evidence gate; owner declaration recorded |

## 7. Mitigation and approval plan

These are completion gates, not statements that the actions have already happened.

| Gate | Owner | Required evidence | Approval condition |
|---|---|---|---|
| G1 — System owner and processing roles | TibaTrace service owner | Verified legal entity, ODPC role/registration, named privacy lead, provider/processor role analysis, product purpose inventory and scale envelope | System provider's own processing and service-provider role are accurately documented |
| G2 — Provider purpose and transparency | TibaTrace service owner with DPO/counsel | Provider-purpose lawful basis record, health-data processing role and safeguards, privacy notice, rights route, service/DPA terms | Provider operations are transparent and customer instructions/roles are contractually defined |
| G3 — Seven-year retention and disposal | TibaTrace service owner | Approved record-class schedule mapping seven years to start triggers/exceptions; configured retention/hold rules; tested primary/object/export/backup deletion, restore reconciliation and service-exit evidence | Retention policy and actual lifecycle behavior agree |
| G4 — Hosting and disclosure | TibaTrace service owner | Hosting/subprocessor names; server/backup countries; support access; contracts/DPAs; data-sharing register; cross-border assessment and safeguards | All storage and recipient paths are disclosed and authorized; unapproved routes remain disabled |
| G5 — Security and resilience | Esenai security/operations owner | Runtime TLS and encryption evidence; attachment/database/backup protection; key custody; malware scanner; privileged access review/MFA; incident contacts/exercise; restore test and RTO/RPO | Controls verified on exact release and production deployment; accepted residual risks signed by accountable owner |
| G6 — Health-sector readiness | TibaTrace product owner | Current [DHA certification guidance](https://certification.dha.go.ke/) and [system categories](https://certification.dha.go.ke/systems); application/certificate and go-live evidence; ODPC registration evidence; completed DPIA; encryption-at-rest and in-transit evidence; system-level health reporting and exchange requirements | Current DHA submission and go-live gates are verified for this solution and production scope before applicable use |
| G7 — Residual risk and prior consultation | System owner, DPO/privacy lead and counsel | Updated risk assessment after G1–G6; stakeholder consultation; explicit residual risk treatment and any ODPC consultation record | Accountable system owner signs; consult the Data Commissioner before processing where section 31(3) applies |

## 8. Consultation, rights and approval record

For this system assessment, consult the product/service owner, DPO/privacy lead, clinical/pharmacy lead, security/operations lead, representative customers/users and patient/community representatives as appropriate. Record who was consulted, date, method, material feedback and how it changed the design or risk assessment. No completed consultation record was included in this review.

Before approval, the system owner must document how a person can find the responsible controller for their records and how a request is securely routed to that controller; separately document requests relating to the provider's own account, staff, security and service records. Verify the route across HQ, POS and support. Record the seven-year retention baseline, applicable exceptions/legal holds and the service/provider's response responsibilities.

| Approval | Name and organization | Decision / conditions | Signature / date |
|---|---|---|---|
| TibaTrace system owner / provider representative | Esenai Group Ltd; Sidney Chepkwony nominated as approval owner | **Pending — not approved** | Pending |
| System DPO/privacy lead | Contact supplied in restricted declaration; appointment/role to verify | **Pending** | Pending |
| Product/clinical-pharmacy lead | Name to assign | **Pending** | Pending |
| Security/operations owner | Name to assign | **Pending** | Pending |
| Legal reviewer | System owner-appointed | **Pending** | Pending |
| Data Commissioner prior consultation, if required | System owner and counsel to determine | Not submitted or evidenced | Pending |

## 9. Review triggers and legal references

Review before a new product purpose or population, significant growth beyond the assessed scale envelope, child/vulnerable group workflow, new integration or recipient, cross-border hosting/support, new profiling/automated decision, material architecture/security change, incident, or changed health-sector requirement. Reassess at least annually while processing continues. Customer-specific processing decisions remain in each customer's separate controller documentation.

This assessment follows the Third Schedule DPIA template and regulations 49–53 of the General Regulations and section 31 of the Act. The official General Regulations were readable and reviewed on 25 October. The scanned ODPC DPIA guidance link was located but could not be fully retrieved; do not claim a complete fresh review of that PDF. Health-sector requirements and certifications must be assessed for the actual solution, facility and exchange.

Regulation 26 addresses Kenya hosting or a Kenya serving copy for specified processing, including primary/secondary healthcare. The legal reviewer must determine the actual applicability and required architecture. Regulations 51–52 describe consultation and consideration of a submitted report, including a provision about no communication within sixty days of submission. No submission receipt, date, complete submitted version or correspondence is attached here; no deemed regulator approval is inferred.

- [Kenya Data Protection Act, 2019, section 31 and related provisions](https://new.kenyalaw.org/akn/ke/act/2019/24/eng@2022-12-31/source)
- [Data Protection (General) Regulations, 2021, including regulations 19, 26, 49–53 and Third Schedule](https://www.odpc.go.ke/wp-content/uploads/2024/03/THE-DATA-PROTECTION-GENERAL-REGULATIONS-2021-1.pdf)
- [ODPC Guidance Note on Data Protection Impact Assessment](https://www.odpc.go.ke/wp-content/uploads/2024/02/ODPC-Guidance-Note-on-Data-Protection-Impact-Assessment-1.pdf)
- [ODPC Guidance Note on the Processing of Health Data](https://www.odpc.go.ke/wp-content/uploads/2024/02/ODPC-Guidance-Note-on-Processing-of-Health-Data.pdf)
- [Digital Health (Health Information Management Procedures) Regulations, 2025](https://new.kenyalaw.org/akn/ke/act/ln/2025/76/eng@2025-04-11/source)
- [Digital Health Agency certification regulatory guide](https://certification.dha.go.ke/regulatory-guide)
- [DHA Certification Program](https://certification.dha.go.ke/) and [Digital Health System Categories](https://certification.dha.go.ke/systems)

This is a compliance work product for review, not legal advice or a regulator decision. No party should mark the DPIA approved until the outstanding gates and signatures are complete.
