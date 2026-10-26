# Exact owner evidence and approvals still required

**Updated:** 26 October 2026.<br>
**Assessment:** TibaTrace system/provider DPIA for Esenai Group Ltd.<br>
**Status:** NOT APPROVED. Fill actual references, dates and signatures; blank
fields and owner declarations are not completed evidence.

## Facts already supplied

Esenai Group Ltd, ODPC processor number `890-695D-435E`, the privacy contact,
Sidney Chepkwony as approval owner, and a seven-year retention baseline are already
recorded. Matching incorporation and ODPC certificate copies were visually
reviewed in restricted storage. You do not need to resend these facts. The
following evidence completes their scope and the still-open controls.

Supply local document paths or references through approved restricted storage.
Do not paste credentials, signing/encryption keys, authenticator seeds, recovery
codes, patient records or unredacted security findings into chat.

| # | What to provide | Exact contents needed | Who approves or verifies it |
|---|---|---|---|
| 1 | Operator/privacy responsibility record | Current registered address; current ODPC processor scope/status verification; controller-role applicability for Esenai's own purposes; DPO/privacy-lead appointment and monitored rights/incident routes; named clinical, security, operations and legal reviewers | Sidney Chepkwony; privacy lead; legal reviewer |
| 2 | Processing-purpose and contract register | Per purpose: Esenai controller/processor role; data/fields; necessity; lawful basis and health-data condition or signed customer instruction; recipients; notices; service/DPA/confidentiality terms; rights-request process. Include patient care, account/workforce, support, security, billing and analytics actually used | Service owner, DPO/legal; customer controller only where its instructions are required |
| 3 | Hosting/location decision and provider records | Kenya host/serving-copy provider, region, actual server endpoint/configuration location and approved architecture; Germany copies and backup/support routes; provider legal entities/countries, DPAs and subprocessors; counsel's signed localization/transfer applicability decision | Infrastructure owner supplies facts; DPO/legal approves applicability and safeguards; owner approves procurement/design |
| 4 | Signed record-class retention schedule | For each class below: exact start event, period, legal/contract basis, child/clinical/tax exception, hold rule, review date, return/deletion/anonymization action, backup expiry and responsible owner | System owner, DPO/legal, clinical/finance leads and controller as applicable |
| 5 | Security and key-custody evidence | Independent report you said passed: assessor, date, tested release/source/digests, server/HQ/native/device/tenant scope, exclusions, findings and retest. Separately provide host/database/object/backup encryption evidence; key owners, access/rotation/compromise policy; custody and recovery independent of the VPS | Independent assessor verifies testing; infrastructure/security owners evidence controls; owner/DPO accepts residual risk |
| 6 | MFA/access activation approval | Named privileged-user list; confirmed authenticator enrollment; secure recovery custodians; two-operator lost-device process; native client upgrade checks; approved enforcement date; access/device/leaver review frequency and signed first review | Each user enrolls; security/identity owner verifies; owner approves enforcement and emergency recovery procedure |
| 7 | Backup/recovery operating approval and report | Approved RPO/RTO, coordinated backup frequency, retention, immutable/off-host destination and country, separate key-recovery location/access owner, alert route, test frequency/capacity. Supply the existing full restore report you said exists: database+objects+keys, release/backup reference, integrity/tenant/business checks, measured time/data loss, provider egress blocked, hold/deletion reconciliation, witness/date and defects closed | Infrastructure/DB/security owners conduct; independent witness verifies; clinical/service owner accepts measured recovery |
| 8 | Malware-scan deferral record | Preserve current deferral. Record accountable owner, affected upload types/tenants, reason, assessed exposure, compensating handling/access controls, expiry/review date, eventual scanner acceptance criteria and DPO/security risk decision. Deferred uploads remain `NOT_SCANNED` | Owner and privacy/security reviewers. Your instruction keeps scanning deferred; it does not supply a dated formal risk-treatment record |
| 9 | Audit/incident operating evidence | Separate append-only audit destination and country; signing-key custody; delivery/continuity/source-integrity monitoring and retained checkpoints; incident on-call contacts, breach/response escalation, exercise date/scenario, results and remediations; signed access review | Security/operations owners; DPO verifies privacy escalation; owner accepts exercise findings |
| 10 | DHA certificate and applicability evidence | Certificate/reference you said exists; issuer, exact system/product category and version, effective/expiry dates, conditions and applicable facility go-live scope. Have scope checked against the issuer. Integrations remain disabled | Product/legal lead obtains; issuer/scope verification by responsible reviewer |
| 11 | Scale/necessity and stakeholder record | Current/annual forecast subjects, prescriptions and transactions; children/vulnerable populations; source/date/assumptions; data minimization/correction/export controls; dated clinical/customer/patient-representative consultation as appropriate and responses | Product and clinical leads; DPO reviews necessity and impacts |
| 12 | Final residual-risk and consultation decision | Exact DPIA version/release/evidence index; each residual risk with owner, treatment, due/review date and restrictions; counsel's decision on required ODPC consultation/submission and receipt/outcome where applicable; dated accountable sign-offs | Sidney Chepkwony, DPO/privacy, clinical, security/operations and legal reviewers under this closure process |

No separate tenant integration credentials are needed while integrations remain
disabled. Future activation requires the tenant/controller's approval, scoped
provider agreement, sandbox/conformance results, endpoint/mapping configuration
and credentials supplied through secure runtime injection. Do not enable an
interface merely to obtain DPIA evidence.

## Retention decision worksheet

For every row, fill **all** fields in the header. The seven-year baseline remains
the recorded starting proposal; this worksheet does not approve it for every
class or choose its start event.

| Class | Start event | Period and authority | Exceptions/holds | Return/disposal action and backup treatment | Owner, reviewer/date, approval reference |
|---|---|---|---|---|---|
| Patient profile and clinical record | PENDING | PENDING | Include minors and clinical continuity | PENDING | PENDING |
| Prescription, dispensing and controlled-medicine record | PENDING | PENDING | PENDING | PENDING | PENDING |
| Identity and practitioner verification evidence | PENDING | PENDING | PENDING | Include lookup digests/encrypted copies | PENDING |
| Payment, sale, refund and tax/accounting record | PENDING | PENDING | PENDING | Preserve legally required reconciled ledgers | PENDING |
| Stock, batch, recall, quarantine and procurement record | PENDING | PENDING | PENDING | PENDING | PENDING |
| Staff account, access and device/session record | PENDING | PENDING | Include leavers and investigations | PENDING | PENDING |
| Security/audit, support and incident record | PENDING | PENDING | Include active investigation/hold | Include external audit copy | PENDING |
| Clinical attachment, derived export and integration journal | PENDING | PENDING | Inherit approved parent rule where applicable | Include object/cached/export copies | PENDING |
| Backup, replica and restored copy | PENDING | PENDING | Include recovery and legal holds | Define expiry and post-restore reconciliation | PENDING |
| Synthetic/demo/test data | PENDING | Exercise-specific proposal | No automatic seven-year assumption | PENDING | PENDING |

Engineering can implement and test the approved schedule after these decisions.
Clinical/financial deletion will not be inferred from “seven years” alone.

## Acceptance record to attach to each approval

Use: **document/reference**, **owner**, **reviewer role/name**, **date**, **exact
release/environment and processing scope**, **decision**, **conditions and review/
expiry date**, **signature or recorded approval route**, and **restricted evidence
location**. A report titled “Passed” without tested scope, findings and retest
details does not close a technical finding.

Evidence already generated by engineering includes rc74 release/health/key/FHIR
acceptance and encrypted archive checks. New source controls and the synthetic
restore rehearsal are described in [technical delivery](25_TECHNICAL_DPIA_CONTROL_DELIVERY_2026-10-26.md).
These do not substitute for the independent assessment, production-scope restore,
hosting decision or the accountable DPIA approval.
