# TibaTrace Data Protection Impact Assessment

**Decision:** NOT APPROVED — TibaTrace system/provider assessment; product-owner operational evidence and accountable sign-off are outstanding  
**Version:** 0.3 (system-scope correction)  
**Assessment date:** 17 October 2026  
**System basis:** working tree based on `45bf133`; compliance documents contain formal production evidence through rc52 (16 October 2026). Object encryption described in this assessment is a local, unshipped change and is not part of that production evidence. RC57 was reported deployed and verified on 17 October 2026 in the deployment task, but its exact release manifest/runtime evidence is not attached here; this assessment does not independently verify the live deployment. On 17 October, 98 targeted security, identity and document-encryption tests passed (5 existing Django deprecation warnings); a fresh rerun of the document-encryption module passed all 9 tests. These are source tests, not a full release pipeline, live test, or penetration test.  
**Assessment owner:** TibaTrace system owner/service provider

## 1. Decision and scope

TibaTrace is designed to process sensitive health information and identifiable clinical, practitioner, payment, stock, and workforce records. Its nature and context meet the high-risk indicators in section 31 of the Data Protection Act and regulation 49 of the Data Protection (General) Regulations, including sensitive health data, potentially vulnerable people and children, large-scale use as tenants grow, and linking clinical and operational records. A DPIA must be completed before the relevant high-risk processing begins and before any materially higher-risk purpose or exchange is activated.

Because the service is already deployed, this is also a remedial system assessment; it does not retrospectively cure any assessment or approval that should have preceded existing processing. The system owner and counsel must review existing use against the applicable requirements.

This assessment is for **TibaTrace as a digital health product and the service-provider processing it performs**. It covers the product design and provider-operated service, including foreseeable patient, practitioner, workforce, operational and security data. It is not an individual customer/tenant's processing assessment and does not make tenant-specific clinical-purpose or lawful-basis decisions. Separate tenant DPIAs may still be required for a controller's own purposes, but tenant sign-off is not the approval basis for this system assessment. See the [TibaTrace system DPIA evidence checklist](19_TIBATRACE_SYSTEM_DPIA_EVIDENCE_CHECKLIST.md) for product-owner evidence still to collect.

The system owner states that TibaTrace is operated in accordance with applicable law and has provided a seven-year retention baseline. This assessment records those as owner representations; it still tests them against documented purposes, record classes, implementation evidence and legal review. “Within the law” is not a substitute for recording the provider's purpose-specific role and lawful basis or customer instructions. Unknown system-owner facts below are blockers, not assumptions. The prioritized closure tests and owners are tracked in the [DPIA gap closure register](20_DPIA_GAP_CLOSURE_REGISTER.md).

The source and release boundary matters: this repository snapshot is rc52-era code; later local drafts and any deployed release require separate review against the exact image digests and runtime configuration. Production host country, subprocessors, active integrations, product-wide scale envelope, and current encryption/backup settings were not proven by this source review.

**Interim decision:** keep the DPIA marked not approved until the system owner supplies the evidence in Section 7 and signs the residual-risk decision. Do not use this draft to claim compliance or to authorize a new health-data exchange. The service owner must verify applicable Digital Health Agency certification and go-live requirements; the source review found no certificate evidence.

## 2. Processing operation and parties

| Field | System-level finding | Required system-owner confirmation |
|---|---|---|
| Project | TibaTrace, a multi-tenant pharmacy/healthcare operations platform with HQ web, Windows and Android POS, Django API, PostgreSQL, Redis/Celery, and clinical-document storage | Record current product version, exact release digests, deployment, enabled modules and assessment date |
| System owner/provider | Existing product documentation identifies Esenai Group Ltd as the vendor; current registered legal name and its role must be verified | Attach company registration, ODPC registration/role evidence, registered address and privacy contact |
| Processing role | For customer patient/facility data, the provider is intended to process data on the relevant health controller's instructions where contracts and actual operations support that role. The provider may be controller for its own workforce, account, billing, service-security and product operations | Confirm role per provider purpose, current service/DPA terms, instructions and whether any independent purpose exists |
| Other parties | Hosting, infrastructure and optional integration recipients are not fully established by the repository review | Verify legal entity, service, access, country, contract and role for each subprocessor/recipient |
| System DPO/privacy lead | Not named in reviewed evidence | Record appointed privacy/DPO lead or documented appointment analysis and contact route |

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

This system assessment covers the foreseeable multi-tenant product scale rather than one customer population. No product-wide capacity envelope or aggregate live count was verified in this source review. The system owner must document the designed/expected deployment range and use aggregate counts for operational monitoring; this does not require patient-level data or make each customer's DPIA part of this product assessment.

### 3.2 As-designed flow and boundaries

1. Health providers, pharmacists and authorized customer personnel enter or update data in HQ/POS; patients or representatives may provide details and prescriptions. Imported data and external source data must be identified and provenance preserved by the relevant workflow.
2. HQ/POS sends requests over the configured HTTPS edge. The API authenticates the actor, resolves tenant context, applies capability checks and tenant-scoped access, then reads/writes the shared-schema PostgreSQL system of record.
3. Redis supports cache and queued work and is not the system of record. Celery workers process tenant-scoped background tasks. Clinical attachments use a separate local object volume in the documented deployment. Current source encrypts new object bytes with AES-256-GCM using a versioned key ID and tenant/object-bound authenticated context; reads verify plaintext hash and require short-lived actor/tenant-bound tokens and capabilities. The production keyring has not been verified here, the legacy-object migration has not been evidenced as complete, and Compose does not prove host/backup-volume encryption or malware scanner operation.
4. Authorized users may use in-product views and reports. Exports, printed records, customer messaging, analytics, support access and manual disclosures are additional system flows; the product owner must document the controls and contracted responsibilities for them.
5. External payment, insurer, regulator, terminology, surveillance or health-information-exchange endpoints are separate trust boundaries. Templates or FHIR routes do not prove a live connection. The system owner must inventory production configuration and traffic. Before activation, document recipient, purpose, minimum fields, lawful authority, country, contract/data-sharing agreement, safeguards, testing and approval.
6. Data deletion/return must follow the approved seven-year baseline, a defined start trigger per record class, legal holds and service exit terms. The reviewed materials do not prove an automated end-to-end deletion lifecycle spanning primary records, attachments, exports, replicas, backups and restoration.

### 3.3 Storage, location, and retention

The documented hosted shape uses a single host, Caddy, application containers, PostgreSQL, Redis, and a clinical-object volume. Deployment documentation identifies a production secret file outside release directories. It does **not** establish the physical host country, legal hosting provider, backup destinations, support access countries, encryption of host/object volumes or backups, or the full subprocessor chain. These are open facts for the service owner to evidence from the live provider account, contracts, and deployment configuration.

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
| Lawfulness, fairness and transparency | Capability checks, masked identity views, draft privacy notice and access audit patterns are documented | Product-owner purposes, bases, notices, ODPC registration, privacy contact, rights route and service-provider role evidence must be confirmed |
| Purpose limitation | Provider templates require explicit activation; this review found no evidence that templates alone transmit data | Verify production integrations and disable unknown routes; the system owner must record each recipient, purpose, agreement and fields |
| Data minimisation | Sensitive identifiers are masked in ordinary views; role/capability separation is documented | Product owner must complete field-to-purpose inventory; validate reports, exports, search, logs and third-party payloads |
| Accuracy | Domain workflows and provenance requirements are documented for selected clinical/terminology information | System owner must document source provenance, correction capabilities and controls for duplicate/incorrect data; customer clinical source-of-truth duties remain outside this product assessment |
| Storage limitation | User-provided seven-year baseline is recorded; draft retention/disposal policy defines lifecycle requirements | Approve record-class triggers/exceptions and implement/test primary/object/export/backup lifecycle and legal holds |
| Integrity and confidentiality | Source and automated tests cover tenant boundary checks, capability enforcement, identifier protection, signed attachment access/integrity/audit, password flows, and scanner fail-closed behavior. New clinical-object writes now use AES-256-GCM with a versioned key ID; production settings require a valid keyring. Production settings also define HTTPS redirects/HSTS/secure cookies and PostgreSQL TLS requirements | Run the matching checks against the exact live release; provision and verify the keyring, migrate legacy objects, verify actual TLS/database/host/backup encryption and key recovery/rotation, active scanner, privileged MFA, access reviews, independent security testing and protected audit delivery. Source/tests do not prove runtime configuration |
| Accountability | Audit models, change/release records and a system document register exist | Name system owners; produce current access, incident, backup/restore, training, DPIA review, provider/subprocessor and disposal evidence; obtain system-owner/legal approval |

For reproducibility, the targeted local test run was `.venv/bin/python -m pytest -q backend/tests/test_document_encryption.py backend/tests/test_infrastructure_security.py backend/tests/test_platform_identity_security.py backend/tests/test_identity_session.py backend/tests/test_password_change.py` (98 passed, 5 warnings on 17 October 2026); `.venv/bin/python -m pytest -q backend/tests/test_document_encryption.py` was rerun separately (9 passed). It exercises selected tenant/document security, encryption/migration, authentication and password behavior; it does not test every API, the deployed release, external providers or independent exploitability. Exact-release security evidence remains open under G5.

## 6. Risk assessment

The assessment uses qualitative likelihood and severity. “High residual / unassessed” means the potential impact is high and evidence is insufficient to claim mitigation; it is not a measured statistical score or accepted risk. The system owner and DPO/privacy lead must validate each risk against the product's scale envelope, deployment, safeguards and consultation.

| Risk scenario | Potential impact on rights/freedoms | Existing safeguards evidenced | Gap / required treatment | Residual status |
|---|---|---|---|---|
| Cross-tenant access or over-privileged user | Confidentiality breach, stigma, discrimination, loss of trust, altered care | Tenant context rejects foreign tenant scope; capability checks and automated cross-tenant/document denial tests are present in source. rc52 release access checks are documented. | Run release tests against exact current live digests; review denial monitoring and complete privileged access reviews | High until current deployment and recurring access evidence supplied |
| Compromised privileged/staff identity or device | Broad disclosure, fraudulent dispensing or untraceable changes | Strong password validation, sign-in/reset throttling, roles/capabilities, token revocation checks, Windows DPAPI and Android Keystore are documented/tested | HQ privileged MFA is not evidenced; verify MFA or an approved time-limited compensating control, leaver/lost-device revocation, and periodic review on the live deployment | High until control and operational evidence supplied |
| Identifier or attachment/key compromise | Patient re-identification, disclosure or loss of matching/access | Patient identifiers are application-encrypted and tenant-digested; new attachment writes are AES-256-GCM encrypted and bound to object key; attachment access is token-bound, hash-checked and audited | Identifier key derives from service secret without managed versioned key ring. Production attachment keyring, legacy-object migration, host/database/backup encryption and key custody are not proven; active scanner is not proven. Verify all layers and rotate/recover keys safely | High; key/storage controls need closure |
| Excessive or insufficient retention/deletion | Intrusion on privacy or loss of clinical/financial evidence | Seven-year baseline stated by system owner; draft schedule and disposal requirements exist | No signed class-specific trigger/exception schedule or end-to-end purge is evidenced. Approve the schedule before implementation; then test purge/return across live stores, exports and backups, including restore reconciliation | High; not approved |
| Unlawful or unexpected disclosure to provider/authority | Loss of confidentiality, rights impact, cross-border transfer breach | Integrations described as fail-closed templates pending activation | Inventory live endpoints, recipients, contracts, countries, payloads and lawful authority; test allowlists and deactivation | High until live inventory and agreement evidence supplied |
| Data inaccuracies or improper clinical use | Wrong medicine, delay, adverse health outcome or misattribution | Audit and selected clinical verification workflows are documented | Establish supported correction/provenance controls and practitioner verification evidence; document customer/source-of-truth responsibilities; validate each clinical module | High for clinical workflows until validated |
| Breach not detected or notified promptly | Prolonged exposure and delayed protection/remedy | Draft incident plan provides response phases and statutory escalation outline | Name responders/DPO and 24/7 contacts; exercise breach/tenant escalation and notification timeline; prove detection coverage | High until operational exercise and contacts exist |
| Service outage, ransomware or unrecoverable data | Interrupted care, lost prescriptions/dispense history, unsafe fallback | rc52 record documents pre-deployment backup and release rollback | Confirm protected recurring backups of database and object files, separate key custody, approved RTO/RPO and full restore exercise | High until recovery evidence and owner approval |
| Unlawful data use for analytics, model training or surveillance | Unexpected profiling, discrimination, sensitive disclosures | No such use is authorized by this assessment; system specifications state provider templates are not active integrations | Prohibit secondary use absent a separate assessed purpose, lawful basis, transparency, safeguards and authorization; verify actual telemetry and exports | High if any unrecorded secondary use exists |
| Digital-health regulatory non-compliance | Unlawful deployment/use or delayed access to health ecosystem | System documentation includes DHA material but no authority-issued certificate or applicability decision is attached | Current [DHA certification guidance](https://certification.dha.go.ke/) says digital health systems used in healthcare facilities require certification and calls for evidence of a completed DPIA plus encryption at rest and in transit. Confirm TibaTrace classification, certificate/go-live scope and any system-level exchange requirements; customer facility duties remain separate | Blocking regulatory gate; status unverified |

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
| TibaTrace system owner / provider representative | Verify legal entity and name | **Pending — not approved** | Pending |
| System DPO/privacy lead | Name or appointment analysis | **Pending** | Pending |
| Product/clinical-pharmacy lead | Name to assign | **Pending** | Pending |
| Security/operations owner | Name to assign | **Pending** | Pending |
| Legal reviewer | System owner-appointed | **Pending** | Pending |
| Data Commissioner prior consultation, if required | System owner and counsel to determine | Not submitted or evidenced | Pending |

## 9. Review triggers and legal references

Review before a new product purpose or population, significant growth beyond the assessed scale envelope, child/vulnerable group workflow, new integration or recipient, cross-border hosting/support, new profiling/automated decision, material architecture/security change, incident, or changed health-sector requirement. Reassess at least annually while processing continues. Customer-specific processing decisions remain in each customer's separate controller documentation.

This assessment follows the Third Schedule DPIA template in regulations 49–51 of the Data Protection (General) Regulations and section 31 of the Data Protection Act. Use the current official text and ODPC guidance during controller/legal sign-off. Health-data and Digital Health Agency requirements must be assessed for the actual facility, solution, use case, and exchange; repository documentation alone does not establish certification.

- [Kenya Data Protection Act, 2019, section 31 and related provisions](https://new.kenyalaw.org/akn/ke/act/2019/24/eng@2022-12-31/source)
- [Data Protection (General) Regulations, 2021, including regulations 49–51 and Third Schedule](https://new.kenyalaw.org/akn/ke/act/ln/2021/263/eng@2022-01-14/source)
- [ODPC Guidance Note on Data Protection Impact Assessment](https://www.odpc.go.ke/wp-content/uploads/2024/02/ODPC-Guidance-Note-on-Data-Protection-Impact-Assessment-1.pdf)
- [ODPC Guidance Note on the Processing of Health Data](https://www.odpc.go.ke/wp-content/uploads/2024/02/ODPC-Guidance-Note-on-Processing-of-Health-Data.pdf)
- [Digital Health (Health Information Management Procedures) Regulations, 2025](https://new.kenyalaw.org/akn/ke/act/ln/2025/76/eng@2025-04-11/source)
- [Digital Health Agency certification regulatory guide](https://certification.dha.go.ke/regulatory-guide)
- [DHA Certification Program](https://certification.dha.go.ke/) and [Digital Health System Categories](https://certification.dha.go.ke/systems)

This is a compliance work product for review, not legal advice or a regulator decision. No party should mark the DPIA approved until the outstanding gates and signatures are complete.
