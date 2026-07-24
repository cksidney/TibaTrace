# Dispensing Lifecycle

```text
DRAFT
→ PREPARING
→ CHECKING
→ READY_FOR_SUPPLY
→ PARTIALLY_SUPPLIED / SUPPLIED
→ CLOSED
```

Alternate states are `ON_HOLD`, `CANCELLED`, `REVERSED`, and `RETURNED`.

An episode identifies prescription, patient, branch, pharmacy inventory location, pharmacist, optional sales order, payment gate, supply method, counselling status, and idempotency key.

Preparation copies the exact prescribed and supplied SKU, FEFO allocation, inventory batch, quantity, package, batch number, expiry, label instruction, substitution, and preparer. No stock issue occurs during preparation.

Final check requires all patient, medicine, strength, form, quantity, batch, expiry, instruction, warning, and package-integrity checks. The preparer cannot be the sole checker. Controlled supply also separates the final checker from the supplying actor.

## Documents and Notifications

The existing protected document store receives the prescription intake record, clinical review summary, intervention record, dispensing worksheet, dispensing label, patient medication information sheet, counselling acknowledgement, controlled supply record, partial-balance record, repeat record, reversal record, and patient-return receipt. Metadata links each artifact to its authoritative prescription and episode and preserves document number, revision, hash, privacy classification, generation time, and barcode payload.

The notification outbox supports rejection, clarification, verification, unavailability, substitution, ready-for-collection, partial supply, repeat timing, expiry, counselling, controlled review, recall follow-up, and return-inspection messages. Payloads exclude medicine and patient identity details.
