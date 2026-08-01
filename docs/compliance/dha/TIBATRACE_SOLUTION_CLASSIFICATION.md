# TibaTrace Solution Classification

**System Designation**: Enterprise Digital Pharmacy, Medicines Management, Clinical Dispensing and Health Supply Chain Platform  
**Governing Framework**: Kenya Digital Health Certification Framework 2025 (Digital Health Agency, Kenya)  
**Baseline Release**: `tibatrace-v0.2.0-rc5` (`f365e778f9f30ab590bc0481c1ea006bb2664cef`)  

---

## 1. System Scope & Classification Overview

TibaTrace is classified as a **Mixed Digital Health Platform** under the Kenya Digital Health Agency (DHA) 2025 Framework. It combines healthcare-worker-facing clinical dispensing, pharmacy information management, commercial supply chain, multi-branch point of sale, clinical decision support (CDS), electronic claims submission, patient-facing handover education, and national health information exchange (HIE) interoperability.

```
+-----------------------------------------------------------------------------------+
|                            TIBATRACE ENTERPRISE PLATFORM                          |
+------------------------------------+----------------------------------------------+
|     PATIENT-FACING SURFACES        |         HEALTHCARE WORKER SURFACES           |
| - Patient Identity & Safety Banner | - HQ Web Back-Office Workspace               |
| - Patient Education & Counselling  | - Windows POS Dispensary & Retail Desktop    |
| - SMS/WhatsApp Collection Proofs   | - Android POS Mobile Dispensary App          |
| - Consent & Data Access Rights     | - Clinical Review & Pharmacist Override      |
+------------------------------------+----------------------------------------------+
|                        SHARED PLATFORM ENGINE & INFRASTRUCTURE                   |
| - FHIR R4 Interoperability Gateway | - Durable Action Journal & Offline Safety    |
| - CDS Drug Interaction Engine      | - Append-Only Immutable Audit Trail          |
| - Multi-Tenant & Multi-Branch RBAC | - FEFO Inventory & GS1 Traceability Module   |
+-----------------------------------------------------------------------------------+
```

---

## 2. Solution Component Mapping

| Subsystem / Surface | Technology Stack | Scope & Classification | Primary Users | Applicable DHA Criteria |
|---|---|---|---|---|
| **Backend REST & FHIR API** | Python / Django REST Framework | Core Platform, CDS Engine, Multi-Tenant Engine, Interoperability Gateway | System Services, POS Apps, HQ Web, External HIE | `DHA-FUNC-001..006`, `DHA-SEC-001..005`, `DHA-INT-001..002` |
| **HQ Web Back-Office** | React / TypeScript | Administrative, Procurement, Enterprise Analytics, Tenant Governance | Pharmacy Managers, Supply Chain Officers, Administrators | `DHA-FUNC-006`, `DHA-REPORT-001`, `DHA-SEC-002` |
| **Windows POS App** | Electron / React / TypeScript | Healthcare-Worker Clinical Dispensing & Retail Checkout Desktop | Pharmacists, Pharmaceutical Technologists, Cashiers | `DHA-FUNC-002..005`, `TT-MTG-OFFLINE-001`, `TT-MTG-GS1-001` |
| **Android POS App** | React Native / TypeScript | Mobile Dispensary & Outward Handover Handheld | Ward Pharmacists, Mobile Dispensary Staff | `DHA-FUNC-002..005`, `TT-MTG-OFFLINE-001` |
| **Patient Safety & Banner** | React / React Native shared components | Patient-Facing Identity & Allergy Verification | Patients & Attending Pharmacists | `DHA-FUNC-001`, `DHA-SEC-004` |
| **FHIR R4 Gateway** | Django / HIE Adapters | Interoperability Exchange (Kenya HIE & e-Claims) | National HIE, Insurers, SHA | `DHA-INT-001..002` |

---

## 3. Surface Category Breakdown

### 3.1 Patient-Facing Components
- **Patient Identity Verification**: Renders full patient name, birth date, and national unique identifier (AfyaYangu UPI) on dedicated patient-facing counter displays.
- **Medication Safety & Counselling**: Displays structured dosage instructions, storage warnings, side-effect notes, and interaction guidance during handover.
- **Privacy & Masking Controls**: Applies dynamic masking on external displays and printed receipts in accordance with the Kenya Data Protection Act 2019.

### 3.2 Non-Patient-Facing / Healthcare-Worker Components
- **Clinical Dispensing & Screening**: Evaluates prescriptions against CDS interaction databases, contraindications, and patient allergy logs.
- **Pharmacist Review & Override**: Offers structured clinical decision logging for pharmacists approving overrides.
- **Inventory & FEFO Allocation**: Enforces server-authoritative First-Expiry-First-Out stock selection and batch quarantine controls.
- **Offline Operations**: Enables governed offline dispensing on POS terminals with multi-constraint safety envelopes.

---

## 4. Architectural Boundaries & Isolation

1. **Tenant Isolation**: Every database table includes `tenant_id` foreign keys indexed and filtered via request-level middleware (`X-Tenant-ID`).
2. **Branch Isolation**: POS terminals operate within a strict `branch_id` context preventing unauthorized inter-branch inventory movements.
3. **Data Protection Boundary**: Patient PII/PHI data dereferencing is restricted to authorized clinical roles; audit logs and export files enforce dynamic redaction.
