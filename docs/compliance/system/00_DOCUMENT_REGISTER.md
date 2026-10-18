# TibaTrace System Compliance Documentation Register

**Document set:** TibaTrace / DawaTrace hosted pharmacy and healthcare platform  
**Prepared:** 17 October 2026  
**Repository snapshot:** `45bf133` on `codex/workflow-gap-closure`  
**Latest formal release record in this repository:** production rc52, dated 16 October 2026; RC57 was reported deployed 17 October, but its manifest/runtime evidence is not in this document set  
**Approval state:** Working drafts; system-owner, legal and independent-assessment approvals remain outstanding. Tenant-specific controller DPIAs are separate.

This register links the requested system documents and says what each one actually establishes. It does not certify TibaTrace, Esenai Group Ltd, or a tenant as compliant. Product controls, organizational controls, customer configuration, and independent test evidence are kept distinct.

The bundled `TibaTrace_System_Documentation_Word.zip` predates the updates in this register and is not a current controlled submission copy. Use the Markdown sources for review and regenerate the Word package after the remaining evidence and approvals are complete.

## Documents

| # | Document | Status |
|---|---|---|
| 1 | [Data Protection Impact Assessment](01_DATA_PROTECTION_IMPACT_ASSESSMENT.md) | Not approved; TibaTrace system/provider DPIA; system-owner production evidence, health-sector proof and sign-off remain blockers |
| 2 | [Privacy Policy](02_PRIVACY_POLICY.md) | Public-facing draft; controller/contact/retention details require confirmation |
| 3 | [System Architecture Diagram](03_SYSTEM_ARCHITECTURE.md) | As-built architecture with deployment evidence boundary stated |
| 4 | [System User Manual](04_SYSTEM_USER_MANUAL.md) | User manual for documented rc52 workflows; verify newer client release before distribution |
| 5 | [Technical Specifications](05_TECHNICAL_SPECIFICATIONS.md) | Repository and documented production specification |
| 6 | [Information Security Policy](06_INFORMATION_SECURITY_POLICY.md) | Policy draft for Esenai and tenant review/approval |
| 7 | [Incident Response Plan](07_INCIDENT_RESPONSE_PLAN.md) | Operational plan draft; named responders and contacts required |
| 8 | [Encryption Implementation Specification](08_ENCRYPTION_IMPLEMENTATION_SPECIFICATION.md) | As-built controls and explicit cryptographic gaps |
| 9 | [Audit Trail Specification](09_AUDIT_TRAIL_SPECIFICATION.md) | As-built application audit model and operating requirements |
| 10 | [Backup and Recovery Policy](10_BACKUP_AND_RECOVERY_POLICY.md) | Policy and recovery procedure; schedules/retention need owner approval |
| 11 | [Disaster Recovery Plan](11_DISASTER_RECOVERY_PLAN.md) | Plan draft; RTO/RPO and exercise evidence outstanding |
| 12 | [Disease Reporting Specification](12_DISEASE_REPORTING_SPECIFICATION.md) | Target specification; no live statutory disease-reporting interface verified |
| 13 | [IDSR Reporting Specification](13_IDSR_REPORTING_SPECIFICATION.md) | Target specification; MoH/County profile and interface acceptance required |
| 14 | [Kenya National Health Terminology Service Compliance Documentation](14_KENYA_NATIONAL_HEALTH_TERMINOLOGY_SERVICE_COMPLIANCE.md) | Mapping and integration assessment; live KNHTS conformance not established |
| 15 | [Access Control Policy](15_ACCESS_CONTROL_POLICY.md) | Policy draft grounded in capability/tenant controls |
| 16 | [Data Retention and Disposal Policy](16_DATA_RETENTION_AND_DISPOSAL_POLICY.md) | Draft; seven-year baseline stated, record-class triggers and operational purge evidence required |
| 17 | [Penetration Testing Report](17_PENETRATION_TESTING_REPORT.md) | No independent penetration test evidence found; this is a transparent status report, not a test result |
| 18 | [Vulnerability Assessment Report](18_VULNERABILITY_ASSESSMENT_REPORT.md) | Limited documentary/source assessment; not a full vulnerability scan or penetration test |
| 19 | [TibaTrace system DPIA evidence checklist](19_TIBATRACE_SYSTEM_DPIA_EVIDENCE_CHECKLIST.md) | System-owner evidence checklist; tenant-specific controller DPIAs remain separate |
| 20 | [TibaTrace system DPIA gap closure register](20_DPIA_GAP_CLOSURE_REGISTER.md) | Prioritized closure evidence, owners and verification tests; not an approval |

## Reading the statuses

- **As-built** describes behavior or architecture visible in the repository and/or in a dated release record. It does not by itself prove every production setting is active.
- **Policy draft** states the control that should govern operations. It becomes an approved policy only after the designated owner adopts it and operational evidence exists.
- **Target specification** defines a safe interface/workflow to implement and validate. It does not mean a regulator connection is available or enabled.
- **Assessment status report** records the assessment boundary and evidence actually available. It must not be represented as independent assurance.

## Facts that govern this document set

1. The last production release with a complete formal verification record in the repository is **rc52** (`e9cac5d`, 16 October 2026). RC57 was reported deployed and verified on 17 October 2026 in the deployment task, but its exact release manifest and runtime evidence are not attached to this compliance set. Attach those before representing RC57 as verified evidence here; do not use candidate source as proof of deployed behavior.
2. The rc52 record documents passing release CI, dependency/image scans without findings, a pre-deployment database backup, runtime checks, and access-control checks. The record is not a penetration-test report or a recurring backup/restore service-level commitment.
3. External provider setup is documented as templates only until approved endpoints, contracts, credentials in the secret manager, and acceptance evidence exist. No live national-registry, insurer, or mobile-money connection is asserted here.
4. Disease/IDSR reporting and KNHTS terminology materials below are specifications and gap statements. They do not claim that TibaTrace currently submits reports to MoH, KHIS, SHIELD, or KNHTS.
5. Before external distribution of this system DPIA, the TibaTrace owner must confirm its legal identity, privacy contact, provider/controller/processor roles, own purposes, data locations, subprocessors, seven-year retention implementation and DHA certification status. Customer controllers separately document their own purposes and legal bases.
6. The TibaTrace system/provider DPIA was revised on 17 October 2026 to map processing, data flows, principles, risks and closure gates to the ODPC DPIA template. It remains **not approved** until the system owner verifies live deployment, hosting, security, backup, seven-year retention implementation and Digital Health Agency evidence, then signs the residual-risk decision. Tenant-specific controller assessments are separate.
7. DHA package files dated 1–2 August 2026 use rc2/rc5/rc10 baselines. Their readiness, compliance-count, scenario-execution and classification statements are historical internal drafts, not Agency findings or current product evidence. They were marked accordingly on 17 October; revalidate them against the exact release and official DHA requirements before submission.

## Source of truth

For implementation details, use the source and current locked manifests. Dated release records remain historical evidence and must not be rewritten to match later software. Principal references include:

- `docs/architecture/TIBATRACE_TECHNICAL_SYSTEM_DOCUMENTATION.md`
- `docs/architecture/DAWATRACE_SECURITY_ARCHITECTURE.md`
- `docs/fhir/KENYA_DATA_PROTECTION_ACT_2019.md`
- `docs/compliance/dha/`
- `docs/releases/RC52_RELEASE_VERIFICATION_2026-10-16.md`
- `docs/releases/TIBATRACE_v1.0.0_RC53.md`
- `docs/operations/EXTERNAL_INTEGRATION_ONBOARDING.md`
- `docs/TIBATRACE_USER_GUIDE.md` (existing detailed guide; its header names rc13, so check the newer manual here for rc52 behavior)

## External legal and standards references

- [Kenya Data Protection Act, 2019, consolidated text](https://new.kenyalaw.org/akn/ke/act/2019/24/eng@2022-12-31/source)
- [Data Protection (General) Regulations, 2021, including the Third Schedule DPIA template](https://new.kenyalaw.org/akn/ke/act/ln/2021/263/eng@2022-01-14/source)
- [ODPC DPIA Guidance Note](https://www.odpc.go.ke/wp-content/uploads/2024/02/ODPC-Guidance-Note-on-Data-Protection-Impact-Assessment-1.pdf)
- [ODPC Guidance Note on the Processing of Health Data](https://www.odpc.go.ke/wp-content/uploads/2024/02/ODPC-Guidance-Note-on-Processing-of-Health-Data.pdf)
- [Digital Health Act, 2023](https://new.kenyalaw.org/akn/ke/act/2023/15/eng@2023-11-24/source)
- [Digital Health (Health Information Management Procedures) Regulations, 2025](https://new.kenyalaw.org/akn/ke/act/ln/2025/76/eng@2025-04-11/source)
- [DHA Certification Regulatory Guide](https://certification.dha.go.ke/regulatory-guide)
- [DHA Certification Program](https://certification.dha.go.ke/) and [Digital Health System Categories](https://certification.dha.go.ke/systems)
- [Kenya National Health Terminology Service](https://nhts.dha.go.ke/) and [KNHTS knowledge base](https://nhts.dha.go.ke/knowledgebase/)
- [Kenya MoH SHIELD surveillance overview](https://shield.health.go.ke/about)
- [MoH and WHO IDSR 3rd-generation guideline training notice](https://www.health.go.ke/joint-effort-moh-and-who-training-boosts-disease-surveillance-four-kenyan-counties)

These references were checked on 17 October 2026. Applicable law and guidance must be rechecked before formal approval or certification submission.
