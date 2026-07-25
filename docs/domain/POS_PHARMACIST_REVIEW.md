# POS Pharmacist Review

When clinical screening identifies high-risk or blocking findings, the POS transaction requires formal pharmacist review before completion.

## Escalation Workflow

1. **Detection**: Cashier encounters a blocking clinical alert during transaction processing.
2. **Escalation Request**: Cashier triggers a pharmacist review request, freezing payment progression.
3. **Pharmacist Authentication**: A qualified pharmacist authenticates at the terminal.
4. **Clinical Evaluation**: Pharmacist reviews findings, patient medication history, and clinical context.
5. **Decision Recording**: Pharmacist selects a formal decision, providing justification if overriding.

## Authentication Methods

Pharmacist verification supports multiple secure authentication factors:
- Standard username/password login
- Secure PIN entry
- NFC / Barcode badge scanning
- Biometric authentication (where supported)
- Supervisor escalation override

## Operational Invariants

- **Segregation of Duties**: The reviewing pharmacist cannot be the same user account as the operating cashier.
- **Decision Types**: Outcomes range from `APPROVE_AS_WRITTEN`, `MODIFIED_REGIMEN`, `COUNSELLED_AND_PROCEEDED`, to `AUTHORIZED_OVERRIDE` and `REJECTED_TRANSACTION`.
