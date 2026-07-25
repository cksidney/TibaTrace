# POS Patient Privacy

The POS patient privacy controls govern clinical data visibility at checkout, enforcing role-based minimum necessary access principles.

## Role-Based Data Visibility

### Cashier View
- Patient full name and patient registration number.
- High-level screening status (CLEAR, WARNING, BLOCKED).
- Actionable pharmacist instructions (e.g., "Refer patient to counter 2").

### Pharmacist View
- Full clinical interaction details and severity scores.
- Patient allergy list and documented adverse reactions.
- Relevant medication history and concurrent active prescriptions.
- Relevant underlying clinical conditions and contraindications.

## Privacy Invariants

- **Data Minimization**: Unrelated clinical diagnoses, sensitive social history, and full national ID numbers are never exposed on POS screens.
- **Unrelated Prescriptions**: Unrelated active or historical prescriptions not relevant to safety screening are hidden.
- **Audit Logging**: Every access to patient clinical profiles or screening details generates an immutable `PosClinicalAuditEvent`.
