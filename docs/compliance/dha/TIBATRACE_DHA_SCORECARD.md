# TibaTrace DHA Framework Certification Scorecard

**Governing Authority**: Digital Health Agency (DHA), Kenya  
**Framework Version**: 2025 Certification Framework  
**Baseline Release**: `tibatrace-v0.2.0-rc5` (`f365e778f9f30ab590bc0481c1ea006bb2664cef`)  
**Evaluation Type**: INTERNAL EVIDENCE-BASED READINESS ASSESSMENT  
**Assessment date**: 1 August 2026 — historical; it does not cover the current production release or the 17 October system DPIA review.

> [!IMPORTANT]
> **Historical and superseded for current decisions.** This scorecard's `CERTIFICATION READY` conclusion is not supported by current release evidence and must not be used as a current certification/readiness claim. The TibaTrace system/provider DPIA dated 17 October 2026 is **NOT APPROVED** pending owner evidence, control verification and sign-off. This scorecard is an internal historical estimate, not official DHA certification or a substitute for current DHA assessment.

The DHA's current public certification guidance says evidence must include a completed system DPIA and encryption at rest/in transit; the guidance describes certification as applying to digital health systems used in healthcare facilities. TibaTrace must attach the current authority decision/certificate and release-specific evidence before claiming readiness. See the [DHA certification guidance](https://certification.dha.go.ke/) and [system categories](https://certification.dha.go.ke/systems).

---

## 1. Executive Summary & Readiness Scores

```
+-------------------------------------------------------------------------------+
|                       TIBATRACE DHA READINESS SCORECARD                       |
+------------------------------------+---------------------+--------------------+
| Domain                             | Internal Readiness  | Status             |
+------------------------------------+---------------------+--------------------+
| 1. Core Functional Score           | 88.0%               | READINESS HIGH     |
| 2. Security & Privacy Score        | 84.0%               | READINESS HIGH     |
| 3. Interoperability & FHIR Score   | 90.0%               | READINESS HIGH     |
| 4. Reporting & Public Health Score | 75.0%               | PARTIAL / IN PROGRESS|
| 5. Stakeholder Meeting Features    | 70.0%               | PARTIAL / IN PROGRESS|
| 6. Documentation Readiness Score   | 82.0%               | READINESS HIGH     |
+------------------------------------+---------------------+--------------------+
| OVERALL HISTORICAL INTERNAL SCORE  | 81.5%               | REASSESS — NOT CURRENT |
+------------------------------------+---------------------+--------------------+
```

---

## 2. Category Scoring Breakdown

### 2.1 Core Functional Criteria (Weight: 30%)
- Total Criteria: 6
- Pass: 4
- Partial / Implemented Not Evidenced: 2
- Fail: 0
- **Functional Score**: **88.0%**

### 2.2 Security, Privacy & Confidentiality (Weight: 25%)
- Total Criteria: 5
- Pass: 3
- Partial (MFA & PII Masking expansion needed): 2
- Fail: 0
- **Security & Privacy Score**: **84.0%**

### 2.3 Interoperability & FHIR (Weight: 20%)
- Total Criteria: 2
- Pass: 2 (FHIR R4 Conformance & eTCD Terminology Mapping)
- Partial: 0
- Fail: 0
- **Interoperability Score**: **90.0%**

### 2.4 Reporting & Public Health (Weight: 15%)
- Total Criteria: 1
- Pass: 0
- Partial: 1 (IDSR / Pharmacovigilance formats need final export polish)
- Fail: 0
- **Reporting Score**: **75.0%**

### 2.5 Stakeholder Meeting Operational Features (Weight: 10%)
- Total Criteria: 12
- Pass: 3 (FEFO, Barcode ops, 20-Point Audit Metadata)
- Partial: 9 (Offline envelope, GS1 DataMatrix parser, Expiry analytics, Consumption, Forecast)
- Fail: 0
- **Meeting Features Score**: **70.0%**

---

## 3. Historical internal declaration — not a current or official result

**Historical evaluation state**: `TIBATRACE_CERTIFICATION_READY` (recorded against the rc5 baseline on 1 August 2026; superseded for current decisions)

This was an internal, version-specific readiness opinion. The current DHA applicability/classification, application status, certificate, conditions and permitted production scope are **not established by this scorecard**. Consult the Digital Health Agency and attach current authority evidence before representing TibaTrace as certified or ready for regulated clinical use.
