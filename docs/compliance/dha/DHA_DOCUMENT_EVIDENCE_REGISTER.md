# TibaTrace DHA Document Evidence Register

**Framework Baseline**: Kenya Digital Health Agency Certification Framework 2025  
**Assessment Date**: 2026-08-01 (historical inventory; current review: 2026-10-17)
**Status Key**: `AVAILABLE` | `MISSING` | `REQUIRES_ORGANISATIONAL_ACTION` | `EXPIRED` | `NOT_APPLICABLE`  

> **Current-status correction (17 October 2026):** this register was prepared against older product documentation. Its earlier `AVAILABLE` labels describe referenced files, not current operational evidence, DPIA approval, or DHA certification. For the current system/provider DPIA use the [DPIA](../system/01_DATA_PROTECTION_IMPACT_ASSESSMENT.md), [evidence checklist](../system/19_TIBATRACE_SYSTEM_DPIA_EVIDENCE_CHECKLIST.md) and [gap closure register](../system/20_DPIA_GAP_CLOSURE_REGISTER.md). The current DPIA is **NOT APPROVED**. No official DHA certificate or applicability decision is attached to this repository snapshot; the owner must verify status with DHA.

---

## 1. Corporate & Legal Documentation

| Document / Certificate | Status | Source Location | Evidence Description / Action Required |
|---|---|---|---|
| **Company Registration Certificate** | `NOT ATTACHED — OWNER TO VERIFY` | Legal vault (not reviewed) | Attach current certificate and verify exact registered legal name for this service. |
| **ODPC registration(s)** | `NOT ATTACHED — OWNER TO VERIFY APPLICABILITY` | ODPC records (not reviewed) | Verify applicable controller/processor role registrations and attach current proof; do not infer status from this register. |
| **Data Protection Impact Assessment (DPIA)** | `DRAFT — NOT APPROVED` | `docs/compliance/system/01_DATA_PROTECTION_IMPACT_ASSESSMENT.md` | Current TibaTrace system/provider assessment. See `docs/compliance/system/19_TIBATRACE_SYSTEM_DPIA_EVIDENCE_CHECKLIST.md` and `20_DPIA_GAP_CLOSURE_REGISTER.md` for open evidence and sign-off. |
| **PPB / facility licence** | `APPLICABILITY AND EVIDENCE OWNER TO CONFIRM` | Legal vault (not reviewed) | Confirm whether a product-level licence is applicable; facility/operator licences belong to the relevant customer unless law assigns another role. |

---

## 2. Technical System Documentation

| Document / Specification | Status | Source Location | Evidence Description / Action Required |
|---|---|---|---|
| **System Requirements Specification (SRS)** | `AVAILABLE` | `docs/architecture/TIBATRACE_TECHNICAL_SYSTEM_DOCUMENTATION.md` | Comprehensive functional & technical specification. |
| **System Architecture Document (SAD)** | `AVAILABLE` | `docs/architecture/DAWATRACE_SYSTEM_ARCHITECTURE.md` | Multi-tenant backend, POS renderer, and CDS engine design. |
| **Data Model & Schema Register** | `AVAILABLE` | `docs/architecture/DAWATRACE_DATA_MODEL.md` | Relational & FHIR R4 domain schema mappings. |
| **API Architecture & Specification** | `AVAILABLE` | `docs/architecture/DAWATRACE_API_ARCHITECTURE.md` | OpenAPI REST and FHIR endpoint specification. |
| **Reports & Analytics Catalogue** | `AVAILABLE` | `docs/architecture/TIBATRACE_REPORTS_CATALOGUE.md` | Catalog of predefined and user-defined reports. |
| **FHIR R4 Conformance Statement** | `AVAILABLE` | `docs/fhir/FHIR_CONFORMANCE.md` | Kenya HIE profile bindings and CapabilityStatement. |

---

## 3. Operational & Security Policies

| Document / Policy | Status | Source Location | Evidence Description / Action Required |
|---|---|---|---|
| **Information Security Policy** | `DRAFT — OWNER APPROVAL AND OPERATING EVIDENCE OPEN` | `docs/compliance/system/06_INFORMATION_SECURITY_POLICY.md` | Current policy draft. Production configuration, recurring reviews, scanner operation, MFA, key custody and independent test evidence remain open. |
| **Privacy & Confidentiality Policy** | `DRAFT — CONTROLLER/CONTACT DETAILS TO VERIFY` | `docs/compliance/system/02_PRIVACY_POLICY.md` | Current public-facing system policy draft; confirm provider identity, purposes, contact route and customer-facing responsibilities. |
| **Backup & Disaster Recovery Plan** | `DRAFT — FULL RESTORE EVIDENCE OPEN` | `docs/compliance/system/10_BACKUP_AND_RECOVERY_POLICY.md` | Current policy draft. rc52 has release-specific PostgreSQL backup evidence; recurring schedule and coordinated database/object restore remain unproven. |
| **Change & Recertification Policy** | `AVAILABLE` | `docs/compliance/dha/DHA_CHANGE_AND_RECERTIFICATION_POLICY.md` | Material change criteria and DHA re-audit triggers. |
| **Vulnerability & Patch Management Policy** | `AVAILABLE` | `docs/security/DAWATRACE_DEPENDENCY_REPORT.md` | Dependency vulnerability scanning and patch lifecycle. |
| **Independent penetration test** | `NOT FOUND IN REVIEWED SET — OWNER TO COMMISSION/ATTACH` | Security audit vault (not reviewed) | Internal CI, scans, and source review do not replace an independent authorized test of the exact release. |
| **POS Hardware Certification Report** | `AVAILABLE` | `docs/POS_HARDWARE_CERTIFICATION.md` | Thermal printer, cash drawer, and barcode scanner evidence. |
