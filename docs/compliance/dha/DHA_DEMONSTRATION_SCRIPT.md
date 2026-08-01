# TibaTrace DHA Certification Live Demonstration Script

**Auditing Agency**: Digital Health Agency (DHA), Kenya  
**System Evaluated**: TibaTrace Enterprise Platform  
**Target Release**: `tibatrace-v0.2.0-rc5`  

---

## Demonstration Flow & Verification Protocol

This script provides step-by-step instructions for a live demonstration of TibaTrace during formal DHA certification audit proceedings.

### Segment 1: Patient Identity & Prescription Loading (10 Mins)
1. Open Windows POS dispensary interface.
2. Select patient **Grace Kamau** (`AfyaYangu UPI: Afya-9982-11`).
3. Verify `PatientSafetyBanner` shows resolved demographics and allergy alert status.
4. Load prescription `DEMO-DISP-8001`.

### Segment 2: Clinical Decision Support & Pharmacist Override (15 Mins)
1. Observe CDS interaction alert generated for `Warfarin + Aspirin`.
2. Demonstrate UI button lock (`ClinicalRail` displaying `"BLOCKING: Contact prescriber"`).
3. Switch to `PharmacistReviewWorkspace`.
4. Demonstrate licensed pharmacist authorization input, license snapshot capture, and structured override submission.
5. Verify clinical rail updates to `SAFE`.

### Segment 3: Batch Verification, GS1 Parsing & FEFO (15 Mins)
1. Navigate to batch verification panel.
2. Scan a simulated GS1 2D DataMatrix barcode `(01)06164000000000(10)BATCH-99(17)251231(21)SN-1002`.
3. Verify automatic parsing of GTIN, Batch Number, Expiry Date, and Serial Number.
4. Attempt to dispense an expired batch -> observe server refusal `"Batch expired - cannot be supplied"`.

### Segment 4: Payment, Controlled Substance & Handover (10 Mins)
1. Navigate to `PaymentPanel` -> process cash transaction with receipt generation.
2. Demonstrate controlled substance dual-witness signature input for narcotic line.
3. Transition episode to `COLLECTED` and verify immutable audit trail generation.

### Segment 5: Governance & FHIR Interoperability (10 Mins)
1. Open HQ Web -> navigate to Enterprise Reports.
2. Generate Pharmacovigilance & IDSR public health export.
3. Query FHIR Gateway `/fhir/r4/MedicationDispense/` -> inspect standard FHIR R4 JSON bundle.
