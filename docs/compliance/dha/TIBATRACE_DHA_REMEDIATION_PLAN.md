# TibaTrace DHA & Stakeholder Gap Remediation Plan

**Framework Baseline**: Kenya Digital Health Agency Certification Framework 2025  
**Assessment Date**: 2026-08-01  
**Target Release for Full Compliance**: `tibatrace-v0.2.0-rc2` / `v0.3.0`  

---

## 1. Remediation Priority Framework

- **P0 — Critical Certification Blocker / Patient Safety Risk**: Must be resolved before submission to DHA test lab.
- **P1 — Mandatory High-Risk Gap**: Required for full score compliance under core framework sections.
- **P2 — Mandatory Medium-Risk Gap**: Operational enhancement or secondary workflow.
- **P3 — Non-Core Enhancement**: Nice-to-have feature or future roadmap item.
- **EXTERNAL — Organisational / Legal Action**: Action required outside source code (ODPC registration, PPB licensing, CREST audit).

---

## 2. Priority Remediation Matrix

### 2.1 Priority P0 Gaps (Critical Certification Blockers)

| Gap ID | Requirement | Current State | Target State | Action Required | Owner | Target Milestone |
|---|---|---|---|---|---|---|
| **GAP-P0-01** | `TT-MTG-OFFLINE-001` | Basic offline queue exists | Multi-envelope offline safety framework | Implement strict 24h duration, 50 transaction count, and KSH 100k limits in `@dawatrace/shared` offline evaluator. | POS Team | `v0.2.0-rc2` |
| **GAP-P0-02** | `TT-MTG-GS1-001` | Single GTIN field on SKU | Standalone GS1 module in `packages/shared/src/gs1/` | Add native GS1 DataMatrix 2D parser for AI 01, AI 10, AI 17, AI 21 and checksum validator. | Supply Chain Lead | `v0.2.0-rc2` |

---

### 2.2 Priority P1 Gaps (Mandatory High-Risk Requirements)

| Gap ID | Requirement | Current State | Target State | Action Required | Owner | Target Milestone |
|---|---|---|---|---|---|---|
| **GAP-P1-01** | `DHA-FUNC-001` | Patient model exists | Verified UPI / AfyaYangu integration | Add validation against Kenya National Unique Patient Identifier format rules. | Core Backend | `v0.2.0-rc2` |
| **GAP-P1-02** | `DHA-FUNC-006` | Basic insurance fields | Full e-Claims pre-authorisation integration | Complete SHA/e-Claim pre-authorisation payload mapping in `ClaimsExchangeService`. | Billing Lead | `v0.2.0-rc2` |
| **GAP-P1-03** | `DHA-SEC-001` | Standard user login | Enforced MFA for admin & clinical override | Implement TOTP/SMS MFA middleware for high-privilege endpoints. | Security Lead | `v0.2.0-rc2` |
| **GAP-P1-04** | `DHA-SEC-004` / `TT-MTG-PRIVACY-001` | Basic UI masking | Dynamic role-based PII masking & link expiry | Expand `PrivacyMaskingEngine` across export renderers; enforce 15-minute download link expiration. | Privacy Lead | `v0.2.0-rc2` |
| **GAP-P1-05** | `DHA-REPORT-001` | Standard CSV/PDF export | IDSR & Pharmacovigilance regulatory reports | Build dedicated IDSR and adverse reaction PDF/Excel report generators in HQ Web. | Analytics Lead | `v0.2.0-rc2` |
| **GAP-P1-06** | `TT-MTG-SEARCH-001` | Generic substring search | Restricted parameterised search | Update `ProductSearchService` to enforce strict query parameter filters. | Catalogue Lead | `v0.2.0-rc2` |
| **GAP-P1-07** | `TT-MTG-RESERVE-001` | Simple basket holds | Complete 7-stage stock reservation lifecycle | Implement `InventoryReservation` state machine and background expiry worker. | Inventory Lead | `v0.2.0-rc2` |
| **GAP-P1-08** | `TT-MTG-EXPIRY-001` | Expiry date snapshots | Interactive Expiry Dashboard with heatmaps | Create Expiry Intelligence Workspace in HQ Web with financial risk calculations. | Analytics Lead | `v0.2.0-rc2` |
| **GAP-P1-09** | `TT-MTG-CONSUMPTION-001` | Basic sales reports | Multi-granularity consumption analytics | Implement `ConsumptionAnalyticsService` supporting breakdown by insurer, diagnosis, and programme. | Analytics Lead | `v0.2.0-rc2` |

---

### 2.3 Priority P2 Gaps & External Organisational Actions

| Gap ID | Requirement | Current State | Target State | Action Required | Owner | Target Milestone |
|---|---|---|---|---|---|---|
| **GAP-P2-01** | `TT-MTG-FORECAST-001` | Reorder point calculation | AI-ready predictive demand forecasting | Implement `DemandForecastService` incorporating lead time and lost demand estimation. | Data Science | `v0.3.0` |
| **GAP-EXT-01** | `DHA-DOC-001` | Unregistered | ODPC Registration | Register TibaTrace corporate entity as Data Controller & Data Processor with ODPC Kenya. | Legal Counsel | External |
| **GAP-EXT-02** | `DHA-DOC-002` | Internal security audit | CREST Penetration Test Report | Commission third-party OWASP/CREST penetration audit. | CISO | External |
