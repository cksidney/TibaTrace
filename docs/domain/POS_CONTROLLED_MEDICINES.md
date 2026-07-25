# POS Controlled Medicines Safety

Controlled substance dispensing at the POS requires specialized safety verifications and regulatory compliance checks.

## Verification Checks

Before processing any controlled medication item, the POS plugin verifies:
- **Valid Prescription**: Presence of an active, verified, unexpired prescription.
- **Prescriber Authority**: Verification of prescribing practitioner's controlled substance licensing.
- **Patient Identity**: Photo ID validation and identity confirmation.
- **Quantity & Dosage Limits**: Strict check against maximum single-dispense thresholds.

## Dispensing Governance

- **Prior Supply Tracking**: Checks central dispense history for recent fills to prevent early refills.
- **Repeat Restrictions**: Validates repeat interval rules and remaining authorized refills.
- **Dual-Sign Off**: Enforces an independent second pharmacist check where branch rules require dual verification.
- **Offline Restrictions**: Controlled medicine dispensing is strictly prohibited whenever POS is operating in offline or limited-cache mode.
