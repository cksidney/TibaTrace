# Kenya eRx / clinical field mappings (for review)

**Status:** Published for review before further converter rewrites (§ mapping policy).  
**IG:** Kenya ePrescription FHIR IG 0.1.0 (clinical). For claim-tied dispense use
`kenya_claims_ig.py` profiles instead.

## MedicationRequest ← `PrescriptionItem`

| Domain field | FHIR element | Notes |
|--------------|--------------|-------|
| `PrescriptionItem.id` | `MedicationRequest.id`, Identifier (lineage) | Keep lineage system; add Kenya prescription-id NamingSystem when issuing to HIE |
| `prescription.status` | `status` | Mapped DRAFT→draft, ISSUED/VERIFIED→active, DISPENSED→completed, … |
| (fixed) | `intent` | `order` |
| `canonical_medicine_id` / name | `medicationReference` or `medicationCodeableConcept` | Prefer RxNorm Coding (+ PPB secondary) on HIE |
| `prescription.patient` | `subject` | Absolute CR URL when CR ID present; else `Patient/{id}` |
| `prescription.practitioner_id` | `requester` | Prefer HWR licence Identifier on Practitioner |
| `prescription.issued_at` | `authoredOn` | ISO 8601 |
| `dosage_instruction` | `dosageInstruction[0].text` | Structured Timing/DoseAndRate still open |
| `quantity`, `refills_authorized` | `dispenseRequest.quantity`, `numberOfRepeatsAllowed` | Unit UCUM when known |

**Kenya eRx mustSupport still open:** richer dosage, encounter link, insurance/coverage
extension when claim-bound.

## MedicationDispense ← `PrescriptionFill`

| Domain field | FHIR element | Notes |
|--------------|--------------|-------|
| `PrescriptionFill.id` | `MedicationDispense.id` | |
| `dispense.status` | `status` | COMPLETED→completed, … |
| medicine id | `medicationReference` | RxNorm + PPB on HIE |
| patient | `subject` | CR absolute URL when linked |
| `item_id` | `authorizingPrescription` | **Present** — required for eRx / Claims dispense |
| `quantity_dispensed` | `quantity` | |
| `dispense.dispensed_at` | `whenHandedOver` | ISO 8601 |
| `dispense.location_id` | `location` | Map facility to MFL / FR when exchanging |

**Reimbursement path:** when this dispense supports a claim, validate against
`fhir.kenyaClaimsIG#0.1.0` MedicationDispense profile (`scripts/validate-fhir-claims-ig.sh`).

## Patient ← `Patient`

| Domain field | FHIR element | Notes |
|--------------|--------------|-------|
| `internal_reference_id` | Identifier (local) | Internal only |
| CR ID on identifiers | Identifier (`…/cr-id`) + preferred absolute Patient URL for subjects | Live CR resolve TBD |
| name / telecom / gender / birthDate | standard R4 | Base R4 for clinical eRx (no invented Patient profile); Claims IG has `ke-eclaims-patient` |

Approve this table before large dosage / terminology converter rewrites.
