# TibaTrace System Compliance Documentation Register

**Document set:** TibaTrace / DawaTrace hosted pharmacy and healthcare platform<br>
**Updated:** 26 October 2026; rc75 deployment acceptance added; the 25 October assessment remains historical evidence<br>
**Current production source:** rc75, `39f3e0651fc21f1e9f017db6e9bbaaf3992640bf`<br>
**Current deployment evidence:** [rc75 acceptance](../../releases/RC75_DEPLOYMENT_2026-10-26.md); exact-source CI/provenance, additive migration, rolled-back synthetic MFA checks, live assets/health and authenticated backup verified; MFA activation remains pending<br>
**Approval state:** Working drafts; system-owner, legal and independent-assessment approvals remain outstanding. Tenant-specific controller DPIAs are separate.

This register links the requested system documents and says what each one actually establishes. It does not certify TibaTrace, Esenai Group Ltd, or a tenant as compliant. Product controls, organizational controls, customer configuration, and independent test evidence are kept distinct.

The bundled `TibaTrace_System_Documentation_Word.zip` predates the updates in this register and is not a current controlled submission copy. Use the Markdown sources for review and regenerate the Word package after the remaining evidence and approvals are complete.

## Documents

| # | Document | Status |
|---|---|---|
| 1 | [Data Protection Impact Assessment](01_DATA_PROTECTION_IMPACT_ASSESSMENT.md) | Not approved; TibaTrace system/provider DPIA; system-owner production evidence, health-sector proof and sign-off remain blockers |
| 2 | [Privacy Policy](02_PRIVACY_POLICY.md) | Public-facing draft; controller/contact/retention details require confirmation |
| 3 | [System Architecture Diagram](03_SYSTEM_ARCHITECTURE.md) | As-built architecture with deployment evidence boundary stated |
| 4 | [System User Manual](04_SYSTEM_USER_MANUAL.md) | Operational guide; server baseline rc75; installed native-client versions still need release-inventory confirmation |
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
| 18 | [Vulnerability Assessment Report](18_VULNERABILITY_ASSESSMENT_REPORT.md) | rc71 CI scan and limited runtime/source review; independent assessment declared by owner, report not attached |
| 19 | [TibaTrace system DPIA evidence checklist](19_TIBATRACE_SYSTEM_DPIA_EVIDENCE_CHECKLIST.md) | System-owner evidence checklist; tenant-specific controller DPIAs remain separate |
| 20 | [TibaTrace system DPIA gap closure register](20_DPIA_GAP_CLOSURE_REGISTER.md) | Prioritized closure evidence, owners and verification tests; not an approval |
| 21 | [DPIA review snapshot](21_DPIA_CURRENT_REVIEW_2026-10-25.md) | Dated 25 October production controls, risk scores, restricted evidence index and approval blockers |
| 22 | [Kenya hosting acceptance plan](22_KENYA_HOSTING_ACCEPTANCE_PLAN.md) | Not executed; owner confirmed Kenya hosting needs arranging |
| 23 | [Identifier key remediation and rollout](23_IDENTIFIER_KEY_REMEDIATION_AND_ROLLOUT.md) | Deployed in rc74; key provisioning, migration and synthetic readback verified; independent assessment and full recovery remain open |
| 24 | [DPIA remaining action plan](24_DPIA_REMAINING_ACTION_PLAN_2026-10-26.md) | Ordered owner checklist with required evidence and closure criteria; no approval implied |
| 25 | [Technical control delivery](25_TECHNICAL_DPIA_CONTROL_DELIVERY_2026-10-26.md) | Server controls deployed in rc75; MFA enrollment/enforcement, native rollout, separate custody and operational approvals remain pending |
| 26 | [Exact owner evidence and approvals](26_OWNER_EVIDENCE_AND_APPROVALS_REQUIRED.md) | Required artifacts, scopes, reviewers and retention worksheet; owner action remains open |

## Reading the statuses

- **As-built** describes behavior or architecture visible in the repository and/or in a dated release record. It does not by itself prove every production setting is active.
- **Policy draft** states the control that should govern operations. It becomes an approved policy only after the designated owner adopts it and operational evidence exists.
- **Target specification** defines a safe interface/workflow to implement and validate. It does not mean a regulator connection is available or enabled.
- **Assessment status report** records the assessment boundary and evidence actually available. It must not be represented as independent assurance.

## Facts that govern this document set

1. The DPIA is version 0.4 and remains NOT APPROVED. Current server evidence is
   rc75; the 25 October rc71 assessment and older rc52/rc57 statements describe
   historical deployments. Native-client/device evidence remains separate.
2. Matching Esenai Group Ltd incorporation and ODPC processor certificates were
   visually reviewed. The owner supplied a privacy contact and nominated Sidney
   Chepkwony as approval owner. Signatures and purpose/role review remain open.
3. The live region is Hetzner Nuremberg, Germany. The owner confirmed Kenya hosting
   needs arranging. Correct this in all submitted notices, architecture and flow
   inventories and execute document 22 before closing the localization gap.
4. The owner declares DHA certification, a passed security assessment and an
   existing restore exercise; the matching reports/reference numbers remain to
   be attached. Do not invent an issuer decision or independent test conclusion.
5. Current runtime evidence verifies selected TLS/security settings, clinical
   object keyring and inactive DHA/RX/checkout paths. Malware scanning is deferred;
   retention lifecycle, privileged MFA, key lifecycle/at-rest custody, full
   independent assurance and coordinated separate-copy recovery remain open.
6. Seven years is the owner's retention baseline, not a completed class-specific
   trigger/exception/hold/backup schedule. No irreversible disposal rules have
   been adopted from an unspecified trigger.
7. The identifier remediation from `f8ea5cd` is deployed in rc74. Independent
   keyrings, additive migration, synthetic key/FHIR acceptance and encrypted
   configuration readback are verified. The 25 October rc71 assessment remains
   historical; DPIA-08 stays PARTIAL pending independent review, storage/custody,
   rotation lifecycle and full recovery evidence. Follow documents 23 and 24.
8. The owner says TibaTrace is DHA certified, its security assessment passed and a
   restore exercise exists. The certificate reference and the security/restore
   reports were not located in the reviewed evidence; record these as declarations
   until the artifacts and scope are checked.
9. The restricted packet is git ignored. The old Word ZIP and August DHA packages
   are historical drafts and must not be submitted as current approved evidence.
   Regenerate submission copies only after the relevant approval/evidence gates.

## Source of truth

For implementation details, use the source and current locked manifests. Dated release records remain historical evidence and must not be rewritten to match later software. Principal references include:

- `docs/architecture/TIBATRACE_TECHNICAL_SYSTEM_DOCUMENTATION.md`
- `docs/architecture/DAWATRACE_SECURITY_ARCHITECTURE.md`
- `docs/fhir/KENYA_DATA_PROTECTION_ACT_2019.md`
- `docs/compliance/dha/`
- `docs/releases/RC52_RELEASE_VERIFICATION_2026-10-16.md`
- `docs/releases/TIBATRACE_v1.0.0_RC53.md`
- `docs/operations/EXTERNAL_INTEGRATION_ONBOARDING.md`
- `docs/TIBATRACE_USER_GUIDE.md` (legacy guide; check the current manual and exact release notes before distribution)

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

The General Regulations, DHA guidance and Hetzner region mapping were checked for the 25 October 2026 production review. The scanned ODPC DPIA guidance could not be fully retrieved. Recheck applicable law, current DHA instructions and certificate scope before formal submission.
