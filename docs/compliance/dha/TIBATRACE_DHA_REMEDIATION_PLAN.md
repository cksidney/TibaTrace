# TibaTrace DHA and privacy remediation plan

**Updated:** 26 October 2026<br>
**System DPIA:** NOT APPROVED<br>
**Production server:** rc71, `2965194a29311314e8a5772adfeee5af8c14a8f2`<br>
**DHA status:** Owner says certified; the certificate/scope was not verified in reviewed evidence.

The prior August 2026 plan targeted rc2/0.3 and included speculative feature and legal claims. Those targets and “gap” labels are withdrawn. Use the current evidence rather than that historic roadmap.

## Work sequence

1. **Verify authority and organizational evidence.** Follow the certificate, ODPC and independent report checklist in [DHA evidence register](DHA_DOCUMENT_EVIDENCE_REGISTER.md). Assign privacy, legal, clinical, security, release and integration owners.
2. **Resolve production hosting and disclosures.** Record the Germany production host, complete the Kenya hosting/legal applicability decision, inventory all data recipients and support/storage countries, and reconcile contracts/notices/live configuration.
3. **Complete the system DPIA.** Fill purpose/role/legal basis or instruction, scale/vulnerable population, necessity, retention, data flow and risk treatment; record consultation and required ODPC process. Keep the finding-level [closure register](../system/20_DPIA_GAP_CLOSURE_REGISTER.md) current.
4. **Approve retention and operational controls.** Define signed class-specific triggers/exceptions/holds before deletion implementation; close privileged MFA, malware scanning, storage-at-rest, key custody, incident and recovery findings with production evidence.
5. **Review and release source changes safely.** Follow the local identifier-key rollout record. `f8ea5cd` is not deployed. Provision keys through the approved secret manager, review, test, deploy and independently verify the exact release before updating DPIA evidence.
6. **Obtain criterion-level DHA mapping.** Ask DHA to confirm system category, applicable current criteria, certificate/version scope and whether any change or facility approval is required. Maintain a release-specific evidence matrix; do not use historical percentages.
7. **Validate tenant integrations only when authorized.** Keep DHA/HIE, RX, payment/tax and other exchanges disabled until each tenant has supplied valid credentials through secure configuration and documented legal, contract, security, mapping, sandbox/conformance and go-live approvals.
8. **Submit/sign the final assessment.** After mitigation, obtain reviewer consultation, legal determination on prior ODPC consultation, complete evidence, residual-risk decisions and dated accountable signatures. No elapsed-time or internal-document rule substitutes for a regulator decision.

The detailed owner actions and closure conditions are in the [DPIA remaining action plan](../system/24_DPIA_REMAINING_ACTION_PLAN_2026-10-26.md). The DHA [regulatory guide](https://certification.dha.go.ke/regulatory-guide) and [system categories](https://certification.dha.go.ke/systems) must be rechecked when submitting; DHA determines its current category/process. This document is an internal plan, not a regulator-approved CAPA or certification result.
