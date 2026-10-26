<!-- TIBATRACE DOCUMENT BRANDING START -->
<p><img src="../brand/tibatrace-logo.jpeg" alt="TibaTrace logo" width="150"> &nbsp; <img src="../brand/esenai-group-logo.png" alt="Esenai Group logo" width="200"></p>

**TibaTrace · Esenai Group Ltd**<br>
Branding edition: 26 October 2026. Assessment dates, evidence scope and approval decisions below remain controlling.
<!-- TIBATRACE DOCUMENT BRANDING END -->

# TibaTrace DHA evidence traceability — current boundary

**Updated:** 26 October 2026<br>
**Production server reviewed:** `1.0.0-rc71`, commit `2965194a29311314e8a5772adfeee5af8c14a8f2`<br>
**Source-only follow-up:** local `f8ea5cd`, not deployed<br>
**Assessment status:** Internal evidence map; not a DHA conformance result. The system DPIA remains **NOT APPROVED**.

The previous rc10 matrix contained internal counts and `COMPLIANT_EVIDENCED` labels that are not authority findings and have not been revalidated against the current release. Those counts are withdrawn from current decisions. This matrix records only the high-level facts verified for the current DPIA boundary and the evidence needed next. DHA must supply/confirm the actual applicable criteria and category before a criterion-level compliance claim is made.

| Domain | Current verified fact | Evidence still required | Current status |
|---|---|---|---|
| Product identity and legal operator | Esenai Group Ltd incorporation and ODPC Data Processor certificate were visually reviewed in restricted evidence; processor number `890-695D-435E` | Issuer/scope confirmation, current address, role analysis, verified DPO appointment/contact route and approved contracts | Partial |
| Privacy impact assessment | System/provider DPIA v0.4 describes system processing and risks | Close blocking DPIA register items; stakeholder consultation; required prior-consultation decision; accountable signatures | Open — not approved |
| Production release identity | Server rc71 images, source, CI run, checksums and provenance were matched in the dated review | Native client/device release inventory and evidence for the exact DHA-submitted version | Server evidence recorded; client gap open |
| Hosting and localization | Audited VPS is in Hetzner Nuremberg, Germany; owner said Kenya hosting needs arranging | Kenya architecture or counsel's documented applicability decision; provider/backup/support countries and contract inventory | Open |
| Authentication, access and tenant boundaries | Selected server controls and CI evidence were reviewed; tenant/capability enforcement is in the codebase | Privileged MFA, recurring account/device reviews, adversarial tenant tests and live operating evidence | Partial/open |
| Encryption and key lifecycle | Live TLS and clinical-object keyring were observed; encrypted release backups exist | Host/database at-rest proof, separate key custody, deployed versioned identifier keys, readback/rotation/restore | Partial/open |
| Clinical documents | Upload/download code and protected object storage are documented; no stored clinical documents were in the audited snapshot | Active malware scanner with clean/infected/unavailable tests, or approved restricted-upload exception; production round-trip evidence | Open — scanning deferred |
| Clinical/dispensing functions | Product includes clinical, prescription and POS workflows; this DPIA audit was not a DHA clinical workflow validation | DHA-confirmed criteria, exact-release witnessed scenarios, synthetic fixtures, safety review and preserved artifacts | Not reassessed |
| National exchange and FHIR | Integration scaffolding exists; reviewed DHA/national/RX/checkout activation is disabled | Per-tenant legal authority, credentials, official profiles/version, sandbox and live conformance, approval and operational monitoring | Disabled pending prerequisites |
| Disease/IDSR/terminology reporting | Target specifications exist | Current authority forms/codes, receiving-endpoint acceptance and DPIA/contract/legal approval | Target only; no live interface verified |
| Audit and incident response | Application audit records and an incident plan draft exist | Independent protected audit delivery/review, named responders, contact-route test and incident exercise | Partial/open |
| Retention and recovery | Seven-year owner baseline and draft backup/retention policies exist | Signed class trigger/exception schedule, lifecycle tests, full DB/object/key restore and measured RPO/RTO | Open |
| Independent assurance | Owner says security assessment passed | Signed report, assessor independence, tested version/scope, findings and retest | Owner-declared; report unlocated |
| DHA certificate and go-live | Owner says TibaTrace is certified | Issuer-verifiable certificate and applicable facility/go-live evidence | Owner-declared; not verified in reviewed material |

## Evidence rule

For each DHA-confirmed criterion, add a row that records the exact authority source and version, applicability, product build, tenant/configuration, test procedure, result, immutable artifact location, reviewer and date. Mark `NOT APPLICABLE` only with a documented DHA or legal applicability basis. Do not treat these broad workstreams or the linked product tests as certification.

Use the [DHA evidence register](DHA_DOCUMENT_EVIDENCE_REGISTER.md), [DPIA closure register](../system/20_DPIA_GAP_CLOSURE_REGISTER.md), and [remaining action plan](../system/24_DPIA_REMAINING_ACTION_PLAN_2026-10-26.md). Keep exchanges disabled until the tenant-specific approval and authority gates are met.
