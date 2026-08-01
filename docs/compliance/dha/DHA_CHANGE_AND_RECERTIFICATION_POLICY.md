# TibaTrace DHA Change and Recertification Governance Policy

**Governing Authority**: Digital Health Agency (DHA), Kenya  
**Framework Version**: 2025 Certification Framework  
**Baseline Release**: `tibatrace-v0.2.0-rc5` (`f365e778f9f30ab590bc0481c1ea006bb2664cef`)  

---

## 1. Purpose and Scope

This policy governs ongoing maintenance, change management, and recertification compliance for TibaTrace. Under the Kenya Digital Health Agency (DHA) 2025 Framework, any material change to system architecture, security controls, clinical decision engines, data structures, or interoperability interfaces requires formal notification and potential re-audit.

---

## 2. Change Classification & Recertification Triggers

### 2.1 Material Changes (Mandatory DHA Recertification Trigger)
A **Material Change** alters the security, clinical safety, data processing, or interoperability posture of TibaTrace and requires formal re-audit by DHA:

1. **Clinical Safety Engine**: Modifications to CDS interaction rules, allergy screening logic, or pharmacist override workflow.
2. **Security & Access Control**: Changes to authentication mechanisms, RBAC permission models, multi-tenant isolation middleware, or encryption protocols.
3. **Interoperability & Data Models**: Alterations to FHIR R4 mapping profiles, national HIE gateway endpoints, or eTCD terminology bindings.
4. **Data Protection & Privacy**: Changes affecting PII/PHI storage, data retention, or patient consent handling under the Data Protection Act 2019.

### 2.2 Minor Operational Changes (Internal Governance Only)
Changes that do not alter core compliance posture (e.g., UI theme updates, performance tuning without schema changes, bug fixes covered by existing test cases) require internal change log documentation only.

---

## 3. Corrective and Preventive Action (CAPA) Lifecycle

```
[ Incident / Finding Identified ]
               │
               ▼
[ Root Cause Analysis (RCA) ] ──► [ CAPA Ticket Created (P0/P1/P2) ]
                                            │
                                            ▼
[ Security & Clinical Safety Review ] ──► [ Code & Test Implementation ]
                                            │
                                            ▼
[ Automated CI Certification Gate ] ──► [ DHA Change Log Update ]
```

1. **Identification**: Security vulnerability findings, clinical edge-case bugs, or DHA audit findings trigger a formal CAPA ticket.
2. **Implementation & Testing**: Remediation changes must include automated test coverage and pass `./scripts/validate_dha_certification.sh`.
3. **Evidence Refresh**: Updated traceability matrices (`docs/compliance/dha/TIBATRACE_DHA_TRACEABILITY_MATRIX.md`) and scorecards are published before release tagging.

---

## 4. Recertification Audit Schedule

- **Annual Routine Recertification**: Full re-assessment scheduled every 12 months from original DHA certification issuance.
- **Triggered Immediate Recertification**: Submitted within 30 days of deploying any Material Change to production.
