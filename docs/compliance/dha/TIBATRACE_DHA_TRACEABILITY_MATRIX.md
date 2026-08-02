# TibaTrace DHA & Stakeholder Requirements Traceability Matrix

**Governing Framework**: Kenya Digital Health Certification Framework 2025  
**Baseline Release Tag**: `tibatrace-v0.2.0-rc10` (`2b086c0`)  
**Integration Branch**: `integration/national-health-regulatory-foundation`  
**Assessment Date**: 2026-08-02  

---

## 1. Traceability Summary

| Compliance Category | Requirement Count | Compliant Evidenced | Implemented Not Evidenced | Partially Compliant | Non-Compliant | Not Applicable |
|---|---|---|---|---|---|---|
| **Clinical & Dispensing (DHA-FUNC)** | 6 | 4 | 1 | 1 | 0 | 0 |
| **Security & Privacy (DHA-SEC)** | 5 | 3 | 0 | 2 | 0 | 0 |
| **Interoperability & FHIR (DHA-INT)** | 2 | 2 | 0 | 0 | 0 | 0 |
| **Reporting & Analytics (DHA-REPORT)** | 1 | 0 | 0 | 1 | 0 | 0 |
| **Meeting Notes & Supply Chain (TT-MTG)** | 12 | 3 | 0 | 9 | 0 | 0 |
| **National Integration Foundation (NIF)** | 9 | 0 | 9 | 0 | 0 | 0 |
| **TOTALS** | **35** | **12** | **10** | **13** | **0** | **0** |

---

## 2. Complete Traceability Matrix

### 2.1 Functional & Clinical Requirements (DHA-FUNC)

| Req ID | Requirement Title | Business Rules & Logic | Backend Models & Services | API Endpoint | UI Surfaces | Tests & Evidence | Compliance Status |
|---|---|---|---|---|---|---|---|
| **DHA-FUNC-001** | Unique Patient Identification | National ID / AfyaYangu UPI lookup, format validation | `Patient` model, `PatientIdentityService` | `GET /api/v1/patients/search/` | `PatientSafetyBanner` | `backend/apps/patients/tests/test_identity.py` | `IMPLEMENTED_NOT_EVIDENCED` |
| **DHA-FUNC-002** | E-Prescription State Machine | Canonical lifecycle: Draft -> Authorised -> Preparing -> Checking -> Paid -> Supplied | `DispensingEpisode`, `DispensingLineDTO`, `workflow.ts` | `POST /api/pos/dispensing/episodes/{id}/transition-state/` | `PrescriptionWorkspace`, `DispensingScreen` | `packages/shared/src/dispensing/workflow.test.ts` | `COMPLIANT_EVIDENCED` |
| **DHA-FUNC-003** | Drug Interaction Alerting | Severity-graded CDS evaluation against allergies & active drugs | `PosClinicalScreening`, `ClinicalInteractionEngine` | `POST /api/pos/clinical-screening/evaluate/` | `ClinicalRail`, `ClinicalSummaryCard` | `apps/pos-windows/src/components/tibatrace/ClinicalRail.test.ts` | `COMPLIANT_EVIDENCED` |
| **DHA-FUNC-004** | Pharmacist Override Governance | Structured justification, license snapshot, signed override object | `PosClinicalOverride`, `PharmacistReviewService` | `POST /api/pos/clinical-screening/{id}/pharmacist-review/` | `ClinicalReviewWorkspace`, `ClinicalReviewScreen` | `apps/pos-windows/src/components/tibatrace/PharmacistReview.test.ts` | `COMPLIANT_EVIDENCED` |
| **DHA-FUNC-005** | Controlled Substance Register | Dual-verification (practitioner + witness) before release | `ControlledMedicineRegister`, `verify_controlled` | `POST /api/pos/dispensing/episodes/{id}/verify-controlled/` | `CounsellingAndCollection`, `DispensingScreen` | `backend/apps/dispensing/tests/test_controlled.py` | `COMPLIANT_EVIDENCED` |
| **DHA-FUNC-006** | Real-Time Claims Integration | Copay split calculation, SHA/e-Claim pre-authorisation | `SalesInvoice`, `ClaimsExchangeService` | `POST /api/v1/claims/preauth/` | `HQ Commercial Pricing Workspace` | `backend/apps/billing/tests/test_claims.py` | `PARTIALLY_COMPLIANT` |

---

### 2.2 Security, Privacy & Confidentiality (DHA-SEC)

| Req ID | Requirement Title | Business Rules & Logic | Backend Models & Services | API Endpoint | UI Surfaces | Tests & Evidence | Compliance Status |
|---|---|---|---|---|---|---|---|
| **DHA-SEC-001** | Multi-Factor Authentication | Password complexity, 90-day rotation, MFA for administrative endpoints | `CustomUser`, `MFAAuthenticationMiddleware` | `POST /api/v1/auth/mfa/verify/` | `LoginScreen`, `HQ Auth Modal` | `backend/apps/accounts/tests/test_mfa.py` | `PARTIALLY_COMPLIANT` |
| **DHA-SEC-002** | Granular RBAC & Segregation | Role capabilities per action; no cashier clinical overrides | `UserRole`, `PermissionGuard`, `sales_rbac` | All API endpoints via `HasCapability` permission | `PermissionGuard` in HQ and POS | `docs/domain/SALES_RBAC_MATRIX.md`, unit tests | `COMPLIANT_EVIDENCED` |
| **DHA-SEC-003** | Multi-Tenant Data Isolation | Mandated tenant_id scoping on all DB queries and cache keys | `TenantScopedModel`, `TenantMiddleware` | Middleware injected header `X-Tenant-ID` | All workspaces | `backend/apps/core/tests/test_tenant_isolation.py` | `COMPLIANT_EVIDENCED` |
| **DHA-SEC-004** | Data Minimisation & Masking | PII/PHI redaction on non-clinical displays and export files | `PrivacyMaskingEngine`, `DataProtectionService` | Middleware response filter | `PatientBanner`, Export renderers | `backend/apps/privacy/tests/test_masking.py` | `PARTIALLY_COMPLIANT` |
| **DHA-SEC-005** | Append-Only Audit Log | Immutable 20-point metadata event capture per transaction | `AuditEvent`, `DurableActionJournal` | `POST /api/v1/audit/events/` | `SyncCentre`, `EpisodeTimeline` | `packages/shared/src/dispensing/durableJournal.test.ts` | `COMPLIANT_EVIDENCED` |

---

### 2.3 Interoperability & FHIR (DHA-INT)

| Req ID | Requirement Title | Business Rules & Logic | Backend Models & Services | API Endpoint | UI Surfaces | Tests & Evidence | Compliance Status |
|---|---|---|---|---|---|---|---|
| **DHA-INT-001** | HL7 FHIR R4 Conformance | Kenya HIE profile mapping (MedicationRequest, Dispense) | `FHIRGatewayService`, `KenyaFHIRSerializer` | `GET /fhir/r4/MedicationDispense/` | N/A (Integration Gateway) | `docs/fhir/FHIR_CONFORMANCE.md`, FHIR tests | `COMPLIANT_EVIDENCED` |
| **DHA-INT-002** | Standard Terminology Mapping | eTCD, RxNorm, and SNOMED-CT binding on SKUs | `MedicineSKU`, `eTCDMappingService` | `GET /api/v1/catalogue/etcd/` | `HQ Procurement Workspace` | `docs/integrations/KE_ETCD_PRODUCT_CATALOGUE.md` | `COMPLIANT_EVIDENCED` |

---

### 2.4 Stakeholder Meeting Requirements (TT-MTG)

| Req ID | Requirement Title | Business Rules & Logic | Backend Models & Services | API Endpoint | UI Surfaces | Tests & Evidence | Compliance Status |
|---|---|---|---|---|---|---|---|
| **TT-MTG-OFFLINE-001** | Governed Offline Framework | Multi-envelope limits (24h time, 50 tx, 100k KSH, max snapshot age) | `DurableActionJournal`, `offlineQueue.ts` | Sync endpoints | `SyncCentre` | `packages/shared/src/dispensing/offlineQueue.test.ts` | `PARTIALLY_COMPLIANT` |
| **TT-MTG-SEARCH-001** | Parameterised Attribute Search | Rejects unindexed wildcards; forces generic/brand/GTIN/SKU filters | `ProductSearchService` | `GET /api/v1/catalogue/search/` | `RetailWorkspace` | `packages/shared/src/design-system/retail.test.ts` | `PARTIALLY_COMPLIANT` |
| **TT-MTG-GS1-001** | GS1 DataMatrix & AI Parsing | Parses AI 01 (GTIN), AI 10 (Batch), AI 17 (Expiry), AI 21 (Serial) | `gs1/parser.ts`, `GS1ValidationService` | `POST /api/v1/gs1/parse/` | `BatchVerification`, Goods Receiving | `packages/shared/src/gs1/parser.test.ts` | `PARTIALLY_COMPLIANT` |
| **TT-MTG-FEFO-001** | Server-Authoritative FEFO | Auto-selects batch by earliest expiry date; blocks quarantined/expired | `FEFOAllocationEngine` | `POST /api/v1/inventory/allocate/` | `PrescriptionWorkspace` | `packages/shared/src/dispensing/fefo.test.ts` | `COMPLIANT_EVIDENCED` |
| **TT-MTG-RESERVE-001** | Reservation Lifecycle | Lifecycle: Requested -> Reserved -> Ready -> Consumed \| Expired | `InventoryReservation`, `ReservationWorker` | `POST /api/v1/inventory/reserve/` | POS Basket | `backend/apps/inventory/tests/test_reservation.py` | `PARTIALLY_COMPLIANT` |
| **TT-MTG-BARCODE-001** | Barcode Operations | Embedded barcode verification across all 9 inventory movements | `BarcodeValidationService` | `POST /api/v1/inventory/scan/` | POS & Receiving screens | `apps/pos-windows/src/state/keyboard.test.ts` | `COMPLIANT_EVIDENCED` |
| **TT-MTG-EXPIRY-001** | Expiry Analytics Dashboard | Age buckets (30/60/90/180+ days), heatmaps, financial risk calculation | `ExpiryAnalyticsService` | `GET /api/v1/analytics/expiry/` | `HQ Enterprise Reports` | `docs/architecture/TIBATRACE_REPORTS_CATALOGUE.md` | `PARTIALLY_COMPLIANT` |
| **TT-MTG-CONSUMPTION-001**| Multi-Granularity Consumption | Tracks daily/weekly/monthly trends by medicine, branch, insurer, diagnosis | `ConsumptionAnalyticsService` | `GET /api/v1/analytics/consumption/` | `HQ Enterprise Reports` | Report generator tests | `PARTIALLY_COMPLIANT` |
| **TT-MTG-FORECAST-001** | Demand Forecasting Engine | Predictive ROP calculation based on lead time, seasonality, lost demand | `DemandForecastService` | `GET /api/v1/analytics/forecast/` | `HQ Enterprise Reports` | Forecast unit tests | `PARTIALLY_COMPLIANT` |
| **TT-MTG-AUDIT-001** | 20-Point Audit Metadata | Captures 20 mandatory contextual fields on all audit entries | `AuditEvent`, `DurableActionJournal` | All APIs | All surfaces | `packages/shared/src/dispensing/telemetry.test.ts` | `COMPLIANT_EVIDENCED` |
| **TT-MTG-PRIVACY-001** | Dynamic PII/PHI Masking | Dynamic masking across UI, PDF, Excel; link expiration in 15 mins | `PrivacyMaskingEngine` | Report download endpoints | All export dialogues | `backend/apps/privacy/tests/test_masking.py` | `PARTIALLY_COMPLIANT` |
| **TT-MTG-CAT-001** | System Designation | Standardized designation in docs, headers, and API specifications | N/A (Documentation) | N/A | Documentation & Headers | `docs/architecture/TIBATRACE_TECHNICAL_SYSTEM_DOCUMENTATION.md` | `COMPLIANT_EVIDENCED` |
| **TT-MTG-POS-ACT-001** | Platform Owner Activation Authority | Platform Owner exclusive approval; tenant roles restricted to request submit/view | `posActivation.ts`, `isPlatformOwnerCapability` | `/api/v1/platform/pos-activations/` | `PosActivationConsole` | `packages/shared/src/dispensing/posActivation.test.ts` | `COMPLIANT_EVIDENCED` |
| **TT-MTG-POS-ACT-002** | Activation Request Lifecycle | Backend state machine (DRAFT -> SUBMITTED -> APPROVED -> ACTIVATED); 1-time challenge | `posActivation.ts`, `canTransitionActivationState` | `/api/v1/platform/pos-activations/requests/` | `PosActivationConsole` | `packages/shared/src/dispensing/posActivation.test.ts` | `COMPLIANT_EVIDENCED` |
| **DHA-SEC-POS-ACT-001** | Device Trust & Startup Gate | Fail-closed POS launch gate (validates fingerprint, tenant, branch, offline lease) | `validatePosStartup`, `validateOfflineLease` | Enrolment endpoints | `PosActivationStartupGate` | `packages/shared/src/dispensing/posActivation.test.ts` | `COMPLIANT_EVIDENCED` |
| **DHA-GOV-POS-ACT-001** | Quota Control & Activation Audit | Quota limits per branch; Platform Owner limit override rationale; 19 audit events | `evaluateActivationQuota`, `AuditEvent` | Platform console APIs | `PosActivationConsole` | `packages/shared/src/dispensing/posActivation.test.ts` | `COMPLIANT_EVIDENCED` |

---

### 2.5 National Integration Foundation (NIF)

> **Truth Label Policy**: All entries in this section are labelled with their empirical operational state.
> `ADAPTER_SCAFFOLDED_NOT_CONNECTED` = code exists, no live connection. Until Platform Owner
> activation is confirmed and sandbox evidence exists, no entry may carry `COMPLIANT_EVIDENCED`.

| Req ID | Requirement Title | Backend Implementation | Truth Label | Evidence | Compliance Status |
|---|---|---|---|---|---|
| **NIF-PHASE-1** | Pharmacy Premises Compliance Reconciliation | `PremisesVerificationRequest`, `PremisesVerificationSnapshot`, `verification_service.py`; management command `reconcile_premises_licences` | `MANUAL_INTERNAL_VERIFICATION` | `backend/apps/pharmacy_network/models.py`, `verification_service.py`, `management/commands/reconcile_premises_licences.py` | `IMPLEMENTED_NOT_EVIDENCED` |
| **NIF-PHASE-2** | National Provider Integration Platform | `ProviderConfiguration`, `IntegrationMessage`, `IntegrationDeadLetter`, `ProviderActivationRequest`, `activation_governance.py` | `ADAPTER_SCAFFOLDED_NOT_CONNECTED` | `backend/apps/integrations/models.py`, `backend/apps/integrations/apps.py` | `IMPLEMENTED_NOT_EVIDENCED` |
| **NIF-PHASE-3** | DHA OAuth 2.0 Client | `DhaOAuthClient` (fail-closed, TLS allow-list, credential masking, token digest logging only) | `ADAPTER_SCAFFOLDED_NOT_CONNECTED` | `backend/apps/prescription/providers/oauth_client.py` | `IMPLEMENTED_NOT_EVIDENCED` |
| **NIF-PHASE-4** | DHA HWR Practitioner Verification | `DhaHwrAdapter`, `HwrVerificationDecision`, risk-based prescribing gate, immutable evidence log | `ADAPTER_SCAFFOLDED_NOT_CONNECTED` | `backend/apps/practitioners/hwr_adapter.py` | `IMPLEMENTED_NOT_EVIDENCED` |
| **NIF-PHASE-5** | PPB Premises Adapter Contract | `PpbAdapter` (MANUAL_GOVERNED, SANDBOX_MOCK, OFFICIAL_API modes); replaces `NotImplementedError` with explicit truth-labeled mode dispatch | `MANUAL_INTERNAL_VERIFICATION` | `backend/apps/pharmacy_network/ppb_adapter.py` | `IMPLEMENTED_NOT_EVIDENCED` |
| **NIF-PHASE-6** | Regulatory Product Status Freshness | `PpbProductStatusResult` projection (`CURRENTLY_VERIFIED`, `STALE`, `SUSPENDED`, `WITHDRAWN`, `EXPIRED`, `UNKNOWN`, `MATCH_REQUIRES_REVIEW`, `NOT_FOUND`) | `SNAPSHOT_IMPORTED_STALENESS_GOVERNED` | `backend/apps/pharmacy_network/ppb_adapter.py` | `IMPLEMENTED_NOT_EVIDENCED` |
| **NIF-PHASE-7** | Regulatory Alerts & Recall Ingestion | `RegulatoryAlert`, `RegulatoryAlertVersion`, `RegulatoryMatchCandidate`, `RegulatoryTenantImpact`, `RegulatoryAction`, `RegulatoryEvidence`, `RegulatoryClosure`; confidence-tier matching, global tenant quarantine, prior-dispense tracing, release workflow | `LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED` | `backend/apps/inventory/recalls/models.py`, `backend/apps/inventory/recalls/services.py` | `IMPLEMENTED_NOT_EVIDENCED` |
| **NIF-PHASE-8** | Integration Reliability Engine | Exponential backoff with jitter, dead-letter queue, circuit breaker (CLOSED/OPEN/HALF_OPEN), rate limits | `ADAPTER_SCAFFOLDED_NOT_CONNECTED` | `backend/apps/integrations/reliability.py` | `IMPLEMENTED_NOT_EVIDENCED` |
| **NIF-PHASE-9** | HQ Integration Command Centre | `IntegrationWorkspace.tsx` with truth-label cards, activation progress, DLQ management; `national_integration.ts` shared types | `ADAPTER_SCAFFOLDED_NOT_CONNECTED` | `apps/hq-web/src/IntegrationWorkspace.tsx`, `packages/shared/src/dispensing/national_integration.ts` | `IMPLEMENTED_NOT_EVIDENCED` |
