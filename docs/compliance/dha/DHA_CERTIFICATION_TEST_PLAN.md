# TibaTrace DHA certification test plan — unexecuted draft

**Updated:** 26 October 2026<br>
**Current production server baseline:** `1.0.0-rc71`, commit `2965194a29311314e8a5772adfeee5af8c14a8f2`<br>
**Test target:** To be set to the exact DHA-approved submission build and client versions before execution<br>
**Status:** Plan only. No tests in this document are represented as executed or passed by DHA or an independent laboratory. The system DPIA remains **NOT APPROVED**.

The previous scenario set was drafted against rc5, included unverified endpoints/test identities and cannot be used as current certification evidence. Obtain DHA's applicable criteria and system category first. Then map each criterion to a versioned test, environment, expected result, artifact and reviewer. The [DHA guide](https://certification.dha.go.ke/regulatory-guide) and current DHA instructions control the actual submission process.

## Test controls

- Use a segregated sandbox and synthetic identities only; do not demonstrate with live patient records or production secrets.
- Record server commit/image digest, database migration level, POS installer hashes and OS/device models for each run.
- Use only DHA/tenant-authorized endpoints and test credentials. Keep national exchanges disabled in production until separate approval.
- Capture request/response metadata with sensitive payloads redacted, audit events, screenshots and logs in restricted evidence storage.
- Record pass, fail, blocked or not applicable per DHA-confirmed criterion. A source test or local simulation is not an external conformance result.

## Proposed scenario coverage to map to DHA criteria

| Area | Scenario families | Minimum observable result/evidence |
|---|---|---|
| Identity and tenant boundary | Create/search a synthetic patient; duplicate/ambiguous identifiers; cross-tenant access denial | Correct tenant-scoped result, explicit denial, no unintended identifier disclosure; audit record |
| Prescription intake | Authorized direct entry and supported file intake; invalid, oversized, malformed and duplicate input | Provenance/source captured; invalid input rejected safely; access and upload state recorded |
| Clinical screening | Allergy/interaction warnings, contraindication and pharmacist review/override | Correct severity and gate; authorized rationale recorded; prohibited actor cannot override |
| Dispensing workflow | Prescription state transitions, preparation, final check, payment, supply, cancellation/reversal | Valid transition only; inventory and clinical history reconcile; attributable audit events |
| Inventory and product traceability | Batch/expiry, quarantine/recall, FEFO and stock adjustment | Expired/quarantined stock blocked; movement and user attribution recorded |
| POS financial controls | Cash/card/M-PESA adapter simulation, split/failed/duplicate payment, refund/void and receipt | Idempotent payment state; no false settlement; immutable receipt/refund linkage; no real charge in sandbox |
| Access/security | Authentication, role/capability denial, session expiry/revocation, MFA, export authorization | Least privilege and fail-closed behavior; no data after revocation; security event captured |
| Privacy/retention | Masking, data export/request routing, expiry/hold and restoration | Minimized disclosure; authorized rights workflow; deletion/hold survives restore as designed |
| Upload protection | Clean, infected, timeout/unavailable and too-large files | Only CLEAN file becomes available; other outcomes remain quarantined/rejected and visible as not scanned/failed |
| FHIR/DHA exchange | Valid/invalid profile, authorization failure, retry, duplicate, timeout, receiver rejection | Correct profile/version and consent/authority; safe retry/idempotency; error and audit trace; sandbox receiver acknowledgment |
| Audit/continuity | High-risk action audit, service interruption, backup/restore and key recovery | Attributable event; measured RPO/RTO; database, object and key recovery reconciled |
| Native client and devices | Supported Windows/Android install/signature, offline boundary, printer/barcode and lock/logout | Signed known build; no secret/data leakage; documented device-specific pass/fail and recovery |

## Execution record template

For every DHA-confirmed criterion, preserve: criterion ID/source/version; applicability decision; exact system/client versions and configuration; preconditions and synthetic fixture IDs; steps; expected and actual results; pass/fail/blocked; sanitized logs/screenshots/test report; defect/remediation/retest references; tester and independent witness; date; and artifact hash/location. Obtain DHA acceptance where its process requires it.

**Execution outcome:** Not run; no result can be inferred from this plan.<br>
**Approvals:** Product owner, clinical safety lead, security/privacy reviewer and DHA test authority — pending.
