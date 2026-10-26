<!-- TIBATRACE DOCUMENT BRANDING START -->
<p><img src="../brand/tibatrace-logo.jpeg" alt="TibaTrace logo" width="150"> &nbsp; <img src="../brand/esenai-group-logo.png" alt="Esenai Group logo" width="200"></p>

**TibaTrace · Esenai Group Ltd**<br>
Branding edition: 26 October 2026. Assessment dates, evidence scope and approval decisions below remain controlling.
<!-- TIBATRACE DOCUMENT BRANDING END -->

# Integrated Disease Surveillance and Response (IDSR) Reporting Specification

**Status:** Proposed conformance specification; implementation, MoH profile approval and live integration are not evidenced  
**Version basis:** Kenya MoH/WHO public material references the 3rd-generation IDSR Technical Guidelines; verify the currently mandated edition and forms before implementation.

## 1. Scope and system boundary

This specification covers a future TibaTrace workflow for authorized facility-level IDSR case-based and aggregate reporting. It does not make TibaTrace an IDSR system, declare it DHA certified, or claim submission to KHIS-2/SHIELD. The provider onboarding record and source review do not show a live IDSR endpoint in the deployed release.

The MoH SHIELD overview describes disease surveillance data integration from EHR and other health systems through API or manual upload, with routine/event-based surveillance and outbreak response use cases. TibaTrace must follow the receiving system's current contract and the County/facility reporting SOP.

## 2. Profiles and reporting modes

Implement separate, versioned profiles for:

1. **Routine aggregate reporting:** facility, reporting period, event/disease code, required demographic strata, totals, deaths and completeness fields as defined by the current official form.
2. **Urgent/event-based reporting:** prompt alert for the specific notifiable event under the official case definition, with the minimum required case detail and escalation path.
3. **Case-based reporting:** only for diseases/events whose official instructions require individual case records; enforce necessary identifiers, confidentiality and recipient role.
4. **Correction and closure:** traceable corrected report, outcome/feedback and closure status without overwriting the original submission.

Do not hard-code deadlines, threshold values, disease lists or MoH form numbers from a historical guide. Load them as approved, dated, versioned reporting rules and keep the approving source.

## 3. Data and workflow contract

The payload must contain the authority-approved facility identifier, reporting period/event dates, coded disease/syndrome and classification, counts or case details, required demographic/location data, reporter/reviewer, source lineage, form/profile version, unique report ID and correction relationship. Direct patient identity is excluded from aggregate mode and included in case-based mode only where required and authorized.

State machine:

`DRAFT → VALIDATED → REVIEWED → APPROVED → QUEUED → SUBMITTED → ACKNOWLEDGED`

Alternative terminal or recovery states include `REJECTED`, `RETRYABLE_FAILURE`, `CORRECTED`, `WITHDRAWN`, and `MANUAL_FOLLOW_UP`. Each transition stores actor/time/evidence. “Submitted” is not “accepted”; only a verifiable recipient receipt produces “acknowledged.”

## 4. Integration requirements

- Obtain current API/file specification, auth, certificates, allow-list, throttles, idempotency and acknowledgement contract from the authorized MoH/County system owner.
- Use TLS, protected service credentials, least-privilege service account and authenticated callbacks or polling.
- Validate code systems and reporting-rule versions; reject unmapped or retired codes pending review.
- Queue with durable delivery state and retry schedule; prevent duplicate submissions and retain request/response metadata without logging unnecessary case payloads.
- Define manual fallback when an endpoint is unavailable and reconcile manual submissions into the report ledger later.
- Prevent a platform owner or one tenant from reading another tenant's line-level surveillance data without explicit lawful authority.

## 5. Responsibilities

| Role | Responsibility |
|---|---|
| Facility surveillance focal person | Validate, review, submit/reconcile reports and follow up with County authority |
| Responsible clinician | Confirm the clinical facts/classification required under current rules |
| Tenant privacy lead/controller | Approve purpose, lawful basis, notice, fields, recipient and retention |
| County/MoH system owner | Supply authoritative data dictionary, forms, case definitions, deadlines and interface contract |
| TibaTrace service owner | Implement secure transport, tenant controls, versioning, audit, error handling and operational support |

## 6. Verification and release gate

Before enablement, retain: approved field mapping; current official forms and code lists; source/version identifiers; legal and DPIA approval; test credentials; test evidence for valid/invalid, duplicate, delayed, rejected, corrected and retry cases; audit evidence; failure/downtime exercise; user training; DPO/security review; and receiving-authority acceptance. A generated CSV/PDF alone is not evidence of an interoperable or legally accepted submission.

## 7. References

- [MoH IDSR 3rd-generation training notice](https://www.health.go.ke/joint-effort-moh-and-who-training-boosts-disease-surveillance-four-kenyan-counties)
- [SHIELD system overview](https://shield.health.go.ke/about)
- Existing DHA scorecard/remediation items mention IDSR/pharmacovigilance report-format gaps: `docs/compliance/dha/TIBATRACE_DHA_SCORECARD.md` and `TIBATRACE_DHA_REMEDIATION_PLAN.md`. Reassess those dated records before certification; do not rewrite historical findings.
