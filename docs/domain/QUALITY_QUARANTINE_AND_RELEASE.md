# Quality Inspection, Quarantine and Release Governance

## Overview

Physical receipt of medicines does not grant stock availability. Quality inspection decisions are explicit domain actions recorded under `ReceivingInspection`.

---

## Quality Inspection Decisions

1. **`RELEASE`**: Batch meets all label, expiry, and temperature criteria. Released for stock availability.
2. **`QUARANTINE`**: Placed on technical hold due to documentation discrepancy, cold-chain excursion, or pending assay.
3. **`REJECT`**: Rejected upon arrival due to physical damage, short expiry, or counterfeit suspicion.
4. **`HOLD_FOR_INVESTIGATION`**: Held for senior pharmacist or regulatory reviewer assessment.
5. **`DESTROY`**: Condemned and routed for controlled disposal.
