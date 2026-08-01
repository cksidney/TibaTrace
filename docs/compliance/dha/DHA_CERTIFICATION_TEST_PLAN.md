# TibaTrace DHA Certification Test Plan & Scenarios

**Governing Framework**: Kenya Digital Health Certification Framework 2025  
**Baseline Release**: `tibatrace-v0.2.0-rc5` (`f365e778f9f30ab590bc0481c1ea006bb2664cef`)  

---

## 1. Certification Test Strategy

This document details the 20 mandatory end-to-end certification scenarios executed to validate TibaTrace against the Digital Health Agency (DHA) framework and Stakeholder Meeting Requirements.

Each scenario defines:
- **Preconditions**: Required tenant, branch, operator role, and initial database state.
- **Steps**: Exact sequence of API calls or UI interactions.
- **Expected Results**: Verifiable success criteria and audit outputs.
- **Evidence Capture**: Generated logs, database rows, or FHIR payloads.

---

## 2. Mandatory Test Scenarios (DHA-SCN-001..020)

### Scenario 1: Patient-Linked Prescription Dispensing (DHA-SCN-001)
- **Preconditions**: Active tenant `TENANT-KE-01`, branch `NAIROBI-HQ`, operator `PHARMACIST-01`.
- **Steps**:
  1. Load prescription `RX-2026-8801` for patient `Grace Kamau` (`UPI: Afya-9982-11`).
  2. Perform CDS screening check (`/api/pos/clinical-screening/evaluate/`).
  3. Prepare medicine lines (`AMOX-500`, 30 capsules).
  4. Collect payment and confirm collection.
- **Expected Result**: Episode transitions through `AUTHORIZED -> PREPARED -> CHECKED -> PAID -> SUPPLIED`.
- **Evidence**: `DispensingEpisode` DB row, `AuditEvent` log.

### Scenario 2: Drug-Interaction Blocker (DHA-SCN-002)
- **Preconditions**: Patient with active prescription for `Warfarin 5mg`.
- **Steps**:
  1. Add `Aspirin 75mg` to prescription lines.
  2. Trigger CDS evaluation.
- **Expected Result**: System returns `BLOCKING` status with finding `Severe Drug Interaction: Warfarin + Aspirin`. UI `ClinicalRail` locks supply button.
- **Evidence**: `PosClinicalFinding` with `severity='BLOCKING'`.

### Scenario 3: Pharmacist Review and Override (DHA-SCN-003)
- **Preconditions**: Active blocking finding from Scenario 2.
- **Steps**:
  1. Operator clicks "Request Pharmacist Review".
  2. Licensed Pharmacist (`PHARMACIST-01`) opens `ClinicalReviewWorkspace`.
  3. Enters clinical justification: *"Co-administration monitored under INR protocol."*
  4. Submits override with license number snapshot.
- **Expected Result**: `PosClinicalOverride` object created; clinical rail status updates to `SAFE`; supply unblocked.
- **Evidence**: `PosClinicalOverride` DB row, audit event with pharmacist ID.

### Scenario 4: Patient Allergy Warning (DHA-SCN-004)
- **Preconditions**: Patient `Grace Kamau` has recorded allergy `Penicillin (Severe anaphylaxis)`.
- **Steps**:
  1. Prescribe `Amoxicillin 500mg`.
  2. Run CDS evaluation.
- **Expected Result**: System flags `KNOWN_ALLERGY` violation; status set to `BLOCKING`.
- **Evidence**: Allergy finding in CDS screening payload.

### Scenario 5: Batch and Expiry Traceability (DHA-SCN-005)
- **Preconditions**: Inventory contains batch `B-9901` (Expiry: 2025-12-31, Expired) and batch `B-9902` (Expiry: 2027-06-30).
- **Steps**:
  1. Scan batch `B-9901` during preparation.
- **Expected Result**: `BatchVerification` rejects batch with reason `"Batch expired - cannot be supplied"`. Scanning `B-9902` succeeds.
- **Evidence**: `BatchVerificationResponse` JSON.

### Scenario 6: Controlled-Medicine Workflow (DHA-SCN-006)
- **Preconditions**: Prescription includes controlled substance `Morphine 10mg Inj`.
- **Steps**:
  1. Transition line to `PREPARED`.
  2. Trigger controlled verification modal.
  3. Enter witness practitioner ID (`PRACT-4402`) and patient ID proof (`ID-992834`).
- **Expected Result**: dual-verification recorded; controlled register updated.
- **Evidence**: `ControlledMedicineRegister` DB row.

### Scenario 7: Insurance Eligibility and Claim (DHA-SCN-007)
- **Preconditions**: Insured patient under `SHA-NHIF-SCHEME`.
- **Steps**:
  1. Verify pre-authorisation code `PRE-88201`.
  2. Calculate commercial pricing and patient copay.
- **Expected Result**: System splits total (e.g. Total: KSH 2,500 -> Insurer: KSH 2,000, Copay: KSH 500).
- **Evidence**: `SalesInvoice` copay breakdown.

### Scenario 8: Privacy and Access Restriction (DHA-SCN-008)
- **Preconditions**: Non-clinical cashier logged in on POS.
- **Steps**:
  1. Attempt to view full clinical notes or patient medical history.
- **Expected Result**: HTTP 403 Forbidden returned; PII data masked on UI screen.
- **Evidence**: Redacted response payload.

### Scenario 9: Cross-Tenant Data Isolation (DHA-SCN-009)
- **Preconditions**: Tenant `TENANT-A` attempts to query episode belonging to `TENANT-B`.
- **Steps**:
  1. Issue GET request `/api/pos/dispensing/episodes/EP-TENANT-B/` with header `X-Tenant-ID: TENANT-A`.
- **Expected Result**: System returns HTTP 404 Not Found.
- **Evidence**: Tenant middleware audit log.

### Scenario 10: Audit Trail Reconstruction (DHA-SCN-10)
- **Preconditions**: Completed dispensing episode `EP-8801`.
- **Steps**:
  1. Query `AuditEvent` trail by correlation ID `CORR-99201`.
- **Expected Result**: Returns 20 mandatory metadata fields for every step from loaded -> payment -> collection.
- **Evidence**: Audit JSON export.

### Scenarios 11-20 Summary
- **Scenario 11 (FHIR Exchange)**: Validates MedicationDispense FHIR bundle against Kenya profile.
- **Scenario 12 (Report Export)**: Tests PDF/Excel generation with dynamic watermark.
- **Scenario 13 (Pharmacovigilance Notification)**: Submits adverse reaction report to MoH/PPB endpoint.
- **Scenario 14 (Backup Restoration)**: Verifies point-in-time snapshot recovery.
- **Scenario 15 (Service Recovery)**: Tests system resilience after database failover.
- **Scenario 16 (Offline POS Resync)**: Tests offline envelope locking and journal sync.
- **Scenario 17 (Breach Simulation)**: Tests automated account lockout on suspicious access.
- **Scenario 18 (Access Revocation)**: Revokes user credentials and verifies immediate session invalidation.
- **Scenario 19 (Change-Log Verification)**: Audits release tag commit signature and migration lineage.
- **Scenario 20 (Data Export Request)**: Generates patient-directed data portability package under ODPC guidelines.
