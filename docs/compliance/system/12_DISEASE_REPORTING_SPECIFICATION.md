# Disease Reporting Specification

**Status:** Target specification and implementation gap statement; not a live reporting feature  
**Scope:** Disease/event reporting from TibaTrace to an authorized public-health recipient

## 1. Current state

The repository includes clinical conditions, observations, diagnostic reports, patient records and general reporting. The review found no verified dedicated disease-surveillance submission workflow or live MoH/KHIS/SHIELD adapter. Existing clinical records or exports must not be described as statutory disease reports. No report is sent automatically by this specification.

Kenya MoH materials describe IDSR using the 3rd-generation technical guidelines and the SHIELD platform as a surveillance data exchange with API and manual upload pathways. The reporting authority must confirm the currently required case definitions, forms, timelines, recipients and interface contract before implementation.

## 2. Goals and boundaries

- Support timely, accurate reporting of notifiable disease and public-health events required of an authorized facility.
- Keep clinical care records separate from surveillance extracts; share only the fields required by the approved form and law.
- Support case-based and aggregate reporting where the approved reporting pathway calls for either.
- Preserve facility, county, reporter, source, approval, corrections and submission outcome.
- Fail closed when the disease code, case definition, reporting authority, destination, or required consent/legal authority is unknown.

## 3. Proposed workflow

1. **Detect:** an authorized clinician/pharmacist records a possible reportable condition or event using an approved coded concept and source evidence.
2. **Validate:** compare against the current, versioned case definition and reporting rule. Do not diagnose from an alert alone.
3. **Review:** route to the designated facility surveillance focal person; urgent alerts may be raised immediately but must not bypass required clinical review or legal authority.
4. **Minimize:** create a reporting record containing only approved case fields; prefer aggregate or pseudonymous data where the recipient and purpose allow.
5. **Approve:** an authorized role checks classification, location, event/report dates, duplication, laboratory status and recipient.
6. **Transmit:** send only through an approved authenticated endpoint or generate the exact validated file for authorized upload. Encrypt transport and retain a receipt/acknowledgement.
7. **Reconcile:** distinguish queued, submitted, acknowledged, rejected, corrected and withdrawn. Retry idempotently; never report an acknowledgement as acceptance without the recipient's authoritative response.
8. **Correct/close:** preserve the original, link the correction, record reason and reviewer, and follow up with the receiving authority.

## 4. Minimum data contract to validate with MoH/County

| Data group | Candidate fields; include only if the official profile requires them |
|---|---|
| Reporting unit | Facility identifier from the approved master facility list; county/subcounty and reporting unit |
| Event | Approved disease/syndrome/event code and code-system version; case classification and rule version |
| Time | Event/onset date, detection date, report date, reporting period and timezone |
| Person/case | Case identifier, age/age band, sex and required clinical fields; direct identifiers only when legally required and recipient-authorized |
| Location | Approved coded residence/event location at the minimum required granularity |
| Clinical/lab | Signs or symptoms, specimen/lab state and outcome only where required |
| Report control | Reporter, reviewer, source record, correction/duplicate relationship, destination, idempotency key and response receipt |

No field in this table is approved for production use until mapped to the governing form/profile and lawful purpose.

## 5. Security and privacy requirements

- Tenant and facility isolation; capability-gated case review and export.
- No bulk export by default. Log every create, view, approval, export, submission, correction and denial.
- Encrypt traffic; authenticate and authorize the recipient; validate certificate, endpoint allow-list, replay protection and idempotency.
- Avoid patient names/national identifiers in routine dashboards, alert subject lines and logs.
- Define lawful basis, retention, recipient, controller/processor relationship and data-sharing agreement before enabling submission.
- Prevent duplicate submissions and provide a visible pending/rejected state; outage must not silently discard urgent notifications.

## 6. Acceptance criteria

Acceptance requires an MoH/County-approved current form/profile and case definitions, legal/privacy review, mapping review, test endpoint and credentials, positive/negative/error/replay tests, authenticated response receipt, audit proof, downtime runbook, trained focal users, and owner sign-off. Until then use the authority-approved current manual pathway and record its evidence outside this specification.

## 7. References

- [MoH/WHO notice on IDSR 3rd-generation guideline training](https://www.health.go.ke/joint-effort-moh-and-who-training-boosts-disease-surveillance-four-kenyan-counties)
- [MoH SHIELD overview](https://shield.health.go.ke/about)
- [Kenya Digital Health Act, 2023](https://new.kenyalaw.org/akn/ke/act/2023/15/eng@2023-11-24/source)
