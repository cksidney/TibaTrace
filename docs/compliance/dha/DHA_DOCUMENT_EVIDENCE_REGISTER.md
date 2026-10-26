# TibaTrace DHA document and evidence register

**Updated:** 26 October 2026<br>
**Current production evidence boundary:** server `1.0.0-rc71`, commit `2965194a29311314e8a5772adfeee5af8c14a8f2`<br>
**Status:** Evidence index only. It is not a DHA application, regulator finding, certificate or go-live approval.

The owner states that TibaTrace is DHA certified. The certificate number, copy, scope, conditions and facility go-live evidence were not located in the reviewed material. This is therefore **owner-declared, not verified in this evidence set**; the missing attachment does not prove the declaration false. The system DPIA remains **NOT APPROVED**. Do not use old `AVAILABLE`, score, or `COMPLIANT_EVIDENCED` labels in historical DHA files as present-day proof.

## Corporate and privacy evidence

| Item | Current evidence status | Required action |
|---|---|---|
| Registered operator | Esenai Group Ltd incorporation certificate visually reviewed in restricted evidence packet | Confirm current address and issuer record; keep copy/hash and current service contracting entity in restricted register |
| ODPC registration | Data Processor `890-695D-435E` certificate visually reviewed; reported validity 15 Oct 2026–15 Oct 2028 | Verify issuer/current scope, other required role registrations and the controller/processor role analysis |
| DPO/privacy contact | Contact supplied by owner; identity/address kept in restricted packet | Verify appointment, monitoring, rights route and breach escalation |
| TibaTrace system DPIA | Draft v0.4; NOT APPROVED | Close [register items](../system/20_DPIA_GAP_CLOSURE_REGISTER.md), complete [action plan](../system/24_DPIA_REMAINING_ACTION_PLAN_2026-10-26.md), consult/sign as applicable |
| Tenant/controller DPIAs | Not maintained by this product-level file | Each controller determines and records its own purposes, bases, population, retention and disclosures |
| PPB/facility licences | Scope and current copies not established here | Verify product/operator obligations separately from each customer facility's licence and superintendent credentials |

## Technical and operational documents

| Evidence group | Documents prepared | Current limitation / next evidence |
|---|---|---|
| Product and architecture | System architecture, technical specification, user manual, API/FHIR documents | Production server boundary is rc71. Verify current signed Windows/Android installers and physical device behavior; older DHA package contents are historical |
| Security and privacy | DPIA, privacy-policy draft, information-security and access-control drafts, encryption specification, audit specification | DPIA and policies are unapproved; privileged MFA, scanner, at-rest protection, key custody, audit export and independent assurance remain open |
| Recovery | Backup/recovery policy and disaster-recovery plan | Owner reports a restore exercise; matching full restore report, RPO/RTO, recurring coordinated backups and independent copy remain unverified |
| Retention and rights | Retention/disposal draft and evidence checklist | Seven years is a baseline only. Approve class triggers/exceptions and prove lifecycle/holds/restore reconciliation |
| Health reporting/interoperability | Disease, IDSR and terminology specifications; FHIR and DHA interface materials | No live MoH/KNHTS/DHA/RX/checkout integration was verified as active. Keep disabled pending authorization and endpoint conformance |
| Independent assurance | Penetration-testing and vulnerability status reports | Owner says assessment passed, but signed report/provider/date/scope/retest evidence was not located |
| DHA pack | Classification draft, requirements catalogue, traceability matrix, scorecard, test plan, demonstration script, change policy | Internal planning materials only. Current category, authority certificate, current exact-release conformance and laboratory/production acceptance are not established by these files |

## DHA certificate verification checklist

Obtain and securely record: certificate/reference number; issuer-verifiable copy or portal record; exact legal system/operator name; system category; assessed product version/build; certificate issue/expiry; conditions and exclusions; approved integrations; facility/tenant scope; and written go-live/production credentials or approval if separate. Ask DHA to resolve any mismatch. Do not infer certification from a submitted application, an internal test plan, or the user's statement alone.

The [DHA certification guide](https://certification.dha.go.ke/regulatory-guide), [current program](https://certification.dha.go.ke/) and [system categories](https://certification.dha.go.ke/systems) are the authority references for the owner to recheck at submission time. DHA determines the applicable category and current workflow.
