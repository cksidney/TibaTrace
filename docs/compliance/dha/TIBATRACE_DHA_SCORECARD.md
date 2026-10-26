# TibaTrace DHA evidence gate status

**Updated:** 26 October 2026<br>
**Production server baseline:** `1.0.0-rc71`, commit `2965194a29311314e8a5772adfeee5af8c14a8f2`<br>
**Local source change:** `f8ea5cd` is not deployed<br>
**Result:** **NOT READY TO REPRESENT AS VERIFIED/APPROVED FROM THIS EVIDENCE SET**. This is not an official DHA score or certification decision.

An August 2026 scorecard reported 81.5% and “CERTIFICATION READY” against rc5. That estimate is withdrawn for current decisions. It was not a DHA finding and must not be used as a readiness claim. The owner states TibaTrace is certified; current certificate and go-live scope were not found or issuer-verified in the reviewed evidence. The system DPIA is **NOT APPROVED**.

## Current gates

| Gate | Evidence state | What must be verified before calling it closed |
|---|---|---|
| Legal identity and ODPC status | Partially evidenced in restricted packet | Issuer/scope check, current registered address, all applicable controller/processor registration and DPO route |
| System DPIA and encryption | **Open** | Approved system DPIA; production evidence of in-transit and at-rest encryption; documented risk treatment and accountable sign-off |
| DHA category and certificate | **Owner-declared; unverified here** | DHA certificate/reference, assessed version, category, conditions, expiry and any separate facility go-live approval |
| Production scope and hosting | **Open** | Reconcile verified Germany deployment with Kenya hosting plan and legal assessment; exact native client inventory and data flows |
| Clinical and dispensing safety | **Not reassessed as a DHA conformance suite** | Map current release to DHA-confirmed criteria; execute witnessed scenarios with synthetic data and retain artifacts |
| HIE / national interfaces | **Disabled in reviewed production** | Tenant authority, credentials, sandbox/live endpoint approval, profile/version, conformance evidence and operational sign-off |
| Security assurance | **Open** | Signed independent test report for exact server/client scope, findings and retest; privileged MFA, malware scanning, access review and audit controls |
| Recovery and retention | **Open** | Full restore evidence with measured RPO/RTO and keys/objects/database; approved class-specific retention schedule and lifecycle proof |
| Policies and operational readiness | **Drafts prepared; not adopted** | Named owners, approval dates, training, incident exercise, live contact paths and recurring control evidence |

## Readiness rule

Do not calculate a percentage from unverified internal criteria. Record each authority-confirmed requirement with its source/version, applicability decision, exact release, test method, artifact, owner and status. A document existing in the repository is not evidence that its control is implemented or that DHA accepted it.

See the [DPIA gap closure register](../system/20_DPIA_GAP_CLOSURE_REGISTER.md), [remaining action plan](../system/24_DPIA_REMAINING_ACTION_PLAN_2026-10-26.md), and [DHA evidence register](DHA_DOCUMENT_EVIDENCE_REGISTER.md). Confirm the current workflow with the [DHA certification guide](https://certification.dha.go.ke/regulatory-guide) and [system categories](https://certification.dha.go.ke/systems).
