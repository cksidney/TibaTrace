# TibaTrace DHA Document Evidence Register

**Framework Baseline**: Kenya Digital Health Agency Certification Framework 2025  
**Assessment Date**: 2026-08-01  
**Status Key**: `AVAILABLE` | `MISSING` | `REQUIRES_ORGANISATIONAL_ACTION` | `EXPIRED` | `NOT_APPLICABLE`  

---

## 1. Corporate & Legal Documentation

| Document / Certificate | Status | Source Location | Evidence Description / Action Required |
|---|---|---|---|
| **Company Registration Certificate** | `REQUIRES_ORGANISATIONAL_ACTION` | Legal Vault | Certificate of Incorporation (Kenya Companies Act) required for formal submission. |
| **Data Controller Registration** | `REQUIRES_ORGANISATIONAL_ACTION` | Data Protection Office | Certificate from the Office of the Data Protection Commissioner (ODPC) Kenya. |
| **Data Processor Registration** | `REQUIRES_ORGANISATIONAL_ACTION` | Data Protection Office | Certificate from ODPC Kenya for multi-tenant cloud processing. |
| **Data Protection Impact Assessment (DPIA)** | `AVAILABLE` | `docs/fhir/KENYA_DATA_PROTECTION_ACT_2019.md` | Formal DPIA for cloud health data processing and clinical dispensing. |
| **Pharmacy and Pois Board (PPB) License** | `REQUIRES_ORGANISATIONAL_ACTION` | Legal Vault | Premises license for digital health & tele-pharmacy operation. |

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
| **Information Security Policy** | `AVAILABLE` | `docs/security/DAWATRACE_SECURITY_REPORT.md` | Core security controls, authentication, and RBAC policy. |
| **Privacy & Confidentiality Policy** | `AVAILABLE` | `docs/domain/PATIENT_IDENTITY_AND_PRIVACY.md` | Patient PII/PHI handling and data minimisation guidelines. |
| **Backup & Disaster Recovery Plan** | `AVAILABLE` | `docs/deployment/TIBATRACE_RELEASE_PACKAGING_WORKFLOW.md` | Append-only database snapshot & restore runbook. |
| **Change & Recertification Policy** | `AVAILABLE` | `docs/compliance/dha/DHA_CHANGE_AND_RECERTIFICATION_POLICY.md` | Material change criteria and DHA re-audit triggers. |
| **Vulnerability & Patch Management Policy** | `AVAILABLE` | `docs/security/DAWATRACE_DEPENDENCY_REPORT.md` | Dependency vulnerability scanning and patch lifecycle. |
| **Penetration Testing Report** | `REQUIRES_ORGANISATIONAL_ACTION` | Security Audit Vault | Third-party CREST/OWASP penetration test report. |
| **POS Hardware Certification Report** | `AVAILABLE` | `docs/POS_HARDWARE_CERTIFICATION.md` | Thermal printer, cash drawer, and barcode scanner evidence. |
