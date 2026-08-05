# Stage 2D.1 Authoritative Services Audit & Service Map

## Overview

This service map classifies all backend domain services required for Stage 2D.1 (Patient Intake, Prescription Validation, Clinical Screening, Pharmacist Review, Substitution Governance, Pricing Resolution, Commercial Order Preparation, Inventory Reservation, and POS Register Readiness).

All required services are natively available in the TibaTrace codebase. No ORM shortcuts or direct balance/state mutations are used.

---

## Service Map Classification Matrix

| Domain Requirement | Authoritative Service Class | Module / File Path | Status Classification | Primary Operational Responsibilities & Notes |
| :--- | :--- | :--- | :--- | :--- |
| **1. Patient Governance** | `PatientGovernanceService` | `apps.patients.services` | **AVAILABLE** | Patient creation, search, identification, demographic classification, and tenant isolation. |
| **2. Practitioner Verification** | `PrescriberGovernanceService` / `VerificationEngine` | `apps.practitioners.services` / `apps.prescription.services.verification_engine` | **AVAILABLE** | Practitioner licence validation, active status checks, and controlled medicine prescribing authority. (Truth label: `MANUAL_INTERNAL_VERIFICATION`). |
| **3. Prescription Intake** | `PrescriptionIntakeService` | `apps.prescription.services.clinical_dispensing` | **AVAILABLE** | Prescription intake (digital, walk-in, scanned), line creation, prescriber association, and initial status assignment. |
| **4. Prescription Validation** | `PrescriptionValidationService` | `apps.prescription.services.clinical_dispensing` | **AVAILABLE** | Validates prescription validity dates, line items, prescriber authority, and controlled medicine requirements. |
| **5. CDS / POS Clinical Screening** | `PosClinicalScreeningService` / `ClinicalDecisionSupportService` | `apps.cds.pos_screening_services` / `apps.cds.services` | **AVAILABLE** | Evaluates active prescription/OTC basket against clinical knowledge base, generating structured clinical findings and evaluations. |
| **6. Drug Interaction Checks** | `DrugInteractionService` / `PosClinicalScreeningService` | `apps.prescription.services.clinical_dispensing` / `apps.cds.pos_screening_services` | **AVAILABLE** | Identifies drug-drug interactions, severity levels (CRITICAL, SEVERE, MODERATE, INFO), and clinical evidence. |
| **7. Allergy Checks** | `PosClinicalScreeningService` / `ClinicalDecisionSupportService` | `apps.cds.pos_screening_services` / `apps.cds.services` | **AVAILABLE** | Screens basket active ingredients against patient recorded allergies and intolerances. |
| **8. Duplicate Therapy Checks** | `PosClinicalScreeningService` / `ClinicalDecisionSupportService` | `apps.cds.pos_screening_services` / `apps.cds.services` | **AVAILABLE** | Flags therapeutic duplication across basket items and active patient medication history. |
| **9. Pharmacist Review** | `PharmacistReviewService` / `PosPharmacistReviewService` | `apps.prescription.services.clinical_dispensing` / `apps.cds.pos_screening_services` | **AVAILABLE** | Governs clinical review tasks, reviewer capability checks, and state transitions (`UNDER_REVIEW`, `APPROVED`, `REJECTED`). |
| **10. Final Verification Check** | `DispensingCheckService` / `PharmacistVerificationService` | `apps.prescription.services.clinical_dispensing` | **AVAILABLE** | Performs final clinical safety verification prior to dispensing readiness. |
| **11. Patient Counselling** | `PatientCounsellingService` | `apps.prescription.services.clinical_dispensing` | **AVAILABLE** | Identifies required counselling topics, delivery acknowledgements, and counselling refusal/acceptance. |
| **12. Clinical Overrides** | `PosClinicalOverrideService` / `PharmacistInterventionService` | `apps.cds.pos_screening_services` / `apps.prescription.services.clinical_dispensing` | **AVAILABLE** | Manages clinical override requests, mandatory reason codes, pharmacist capability checks, and override approvals/rejections. |
| **13. Substitution Governance** | `ClinicalSubstitutionService` / `SubstitutionProposalService` | `apps.prescription.services.clinical_dispensing` / `apps.sales.services` | **AVAILABLE** | Evaluates generic substitution eligibility based on active ingredients, dosage form, strength, and patient/prescriber consent. |
| **14. Commercial Quotations** | `QuotationService` | `apps.sales.services` | **AVAILABLE** | Creates commercial price quotations (`DRAFT`, `QUOTED`, `ACCEPTED`, `EXPIRED`, `CANCELLED`). |
| **15. Commercial Sales Orders** | `SalesOrderService` | `apps.sales.services` | **AVAILABLE** | Prepares draft commercial sales orders derived from quotations or direct OTC requests. |
| **16. Pricing Resolution** | `PriceResolutionService` | `apps.pricing.resolution` | **AVAILABLE** | Resolves line pricing across retail price lists, branch prices, insurer tariffs, corporate contracts, and promotions. |
| **17. Branch Pricing Overrides** | `PriceResolutionService` / `CommercialPricingService` | `apps.pricing.resolution` / `apps.sales.services` | **AVAILABLE** | Resolves location-specific branch price books and local price overrides. |
| **18. Promotions & Discounts** | `PriceResolutionService` / `CommercialPricingService` | `apps.pricing.resolution` / `apps.sales.services` | **AVAILABLE** | Applies active promotional rules, volume discounts, and campaign price adjustments. |
| **19. Stock Reservations** | `InventoryReservationService` | `apps.inventory.services` | **AVAILABLE** | Reserves inventory stock, locking available quantity without mutating on_hand balance or ledger entries. |
| **20. FEFO Allocation** | `FEFOAllocationService` | `apps.inventory.services` | **AVAILABLE** | Allocates stock strictly by earliest expiry date (`expiry_date ASC, batch_id ASC`), excluding quarantined, held, recalled, or expired stock. |
| **21. Register & Shift Readiness** | `RegisterAuthorityService` / `RegisterOpeningService` | `apps.pos_shift.authority` / `apps.pos_shift.operations` | **AVAILABLE** | Resolves and validates register state, active business day, open register session, operator shift, and cashier capabilities. |
| **22. POS Device Activation** | `RegisterAuthorityService` / `check_premises_compliance` | `apps.pos_shift.authority` / `apps.pharmacy_network.verification_service` | **AVAILABLE** | Validates registered device assignment to active POS register and premises verification state (`POS_DEVICE_ACTIVATION`). |

---

## Architectural Principles & Gate Rules

A dispensing episode is marked **READY_FOR_PAYMENT** if and only if all gate conditions evaluate to true:

$$\text{Readiness} = \text{clinical\_ready} \land \text{commercial\_ready} \land \text{inventory\_ready} \land \text{register\_ready} \land \text{practitioner\_valid} \land \text{premises\_compliant} \land \text{device\_valid}$$

### Stop Boundary for Stage 2D.1
- **No Payment Settlement**: No payment transactions, M-Pesa receipts, or cash settlements.
- **No Stock Issue**: No `ISSUE` ledger entries, no balance reductions.
- **No Dispensing Completion**: No prescription status set to `DISPENSED` or `FULFILLED`.
- **No Final Receipt / Claim**: No customer receipt generation, no SHA or insurer claim submission.
