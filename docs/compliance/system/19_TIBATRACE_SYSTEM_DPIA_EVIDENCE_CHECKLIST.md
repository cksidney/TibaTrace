# TibaTrace system DPIA evidence checklist

**Purpose:** Complete the product-owner evidence for the TibaTrace system/provider DPIA. This is not a tenant-specific controller assessment.<br>
**Status:** Evidence collection for the system owner; DPIA remains **Not Approved** until the approval gate is met.<br>
**Handling:** Store in the restricted TibaTrace compliance repository. Use aggregate scale figures and configuration locations. Do not include patient records, credentials, API keys or passwords.

The system owner has stated that TibaTrace operates within applicable law and provided a **seven-year retention baseline**. This checklist converts those statements into auditable system evidence. If a fact is unknown, mark it **OPEN**, name an owner, and state whether the related product feature or integration remains disabled. Use the [DPIA gap closure register](20_DPIA_GAP_CLOSURE_REGISTER.md) for priority, closure test and execution order.

## Current evidence update: 25 October 2026

Use the [current review](21_DPIA_CURRENT_REVIEW_2026-10-25.md) and v0.4
[closure register](20_DPIA_GAP_CLOSURE_REGISTER.md) for current dispositions.
Matching incorporation and ODPC processor documents are now reviewed; contact and
approval owner supplied; rc71 server/CI/provenance, selected runtime controls and
aggregate current scale verified. The live host is Germany and the owner confirmed
Kenya hosting needs arranging. Seven years remains a baseline without triggers.
DHA/security/restore conclusions are owner-declared pending attached reports.
The detailed tables below are the remaining evidence workbook, not a claim that
items already supplied are wholly unknown. Private evidence/contacts are in the
restricted packet indexed by document 21; do not publish that packet.

## A. System owner and product identity

| Required evidence | Owner entry / status |
|---|---|
| Registered legal name of TibaTrace owner/operator, registration number and address | `[PARTIAL — matching incorporation certificate reviewed; current address/issuer confirmation and contract role review remain]` |
| ODPC registration role(s), number, date and scope | `[DOCUMENT REVIEWED — Data Processor 890-695D-435E; valid 15 October 2026 to 15 October 2028; issuer check/additional role applicability remain]` |
| Named system DPO/privacy lead and contact; appointment analysis if none | `[PARTIAL — owner supplied contact; appointment/route verification remains]` |
| Named service owner, security/operations lead, product/clinical lead and legal reviewer | `[OPEN]` |
| Processor/controller role analysis per provider purpose, based on contracts and actual operations | `[OPEN — attach approved ROPA and current DPA/service terms]` |
| Current production release/image digests, environments, modules and platform boundaries | `[PARTIAL — rc71 hosted server identity/digests verified; native-client/device scope remains]` |
| Design capacity/target scale and expected data-subject and event volumes; source/date/assumptions | `[OPEN — aggregate forecast; no patient-level data]` |
| System-level assessment owner, date, version, review date and change triggers | `[RECORDED — v0.4, 25 October 2026, Esenai Group Ltd / owner-nominated Sidney Chepkwony; triggers in DPIA section 9; signed decision pending]` |

## B. System purposes and processing roles

Document each purpose performed by TibaTrace itself, and separately identify customer purposes for which TibaTrace acts only under documented instructions. The system owner represents that operations are lawful; attach the provider's purpose/legal-basis record rather than relying only on that statement.

| Processing activity | TibaTrace role: controller or processor | Purpose and necessity | Categories/fields processed | Provider lawful basis or customer instruction | Notice/contract/control | Owner/evidence |
|---|---|---|---|---|---|---|
| Hosting and technical processing of patient records | `[OPEN per service contract]` | `[OPEN]` | `[OPEN]` | `[Customer controller instruction/reference]` | `[DPA/service term]` | `[OPEN]` |
| Identity, tenancy and access administration | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[Privacy notice/access policy]` | `[OPEN]` |
| Platform security, abuse prevention and incident response | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[Notice/retention/control]` | `[OPEN]` |
| Billing, support and service communications | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[Contract/notice]` | `[OPEN]` |
| Product analytics, diagnostics, research, model training or secondary use | `[Confirm whether any such processing occurs; state disabled if none]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Provider-operated integration or exchange | `[One row per configured integration, or “none enabled” with verification]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[Agreement/approval]` | `[OPEN]` |

For health data, identify who handles it under the health-provider/professional-secrecy condition and how TibaTrace's processor access is confined to customer instructions, support authorization, security, and contract. Do not assert a tenant's lawful basis on its behalf.

## C. System data subjects, categories and scale

| Group | System design coverage | Expected scale/capacity | Evidence/source/date | Special safeguards |
|---|---|---|---|---|
| Patients/clients, including children or vulnerable people | `[Confirm categories and modules]` | `[OPEN — aggregate design/forecast]` | `[OPEN]` | `[Age/representative handling and minimization]` |
| Practitioners/prescribers | `[Confirm credential and activity data]` | `[OPEN]` | `[OPEN]` | `[Verification/source/correction controls]` |
| Customer workforce and TibaTrace workforce | `[Confirm account, role, device and audit categories]` | `[OPEN]` | `[OPEN]` | `[Least privilege, notice, access review]` |
| Customers, suppliers, claimants and contacts | `[Confirm enabled commerce modules]` | `[OPEN]` | `[OPEN]` | `[Minimize link to health record]` |

Use capacity envelope and aggregate counts across the platform. Do not include names or row-level records. Explain whether scale is current production, target capacity or a forecast.

## D. End-to-end data flow and provider/subprocessor register

Map collection, API access, database, Redis/queues, clinical objects, logs, reports/exports, backups, support and deletion. Identify each provider that can store, route, access or receive personal data and each country of storage or remote support.

| Provider/legal entity | Service and data access | TibaTrace role / provider role | Live database/object/backup country | Support-access countries | Contract/DPA/transfer safeguards | Production status / evidence |
|---|---|---|---|---|---|---|
| Hosting/VPS/cloud provider | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Backup/storage provider | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Email/SMS/monitoring/support provider | `[OPEN or none]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Payment/financial provider | `[OPEN or none]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Health/regulator/insurer/HIE recipient | `[One row per active interface; or confirm none]` | `[Recipient/processor roles]` | `[Country]` | `[Country]` | `[Authority, DSA, contract, transfer safeguards]` | `[Verified config and transaction evidence]` |

Reconcile this list to production configuration, invoices/contracts, host volumes and backup inventory. A code template, endpoint in source, or planned integration is not evidence of a live data transfer. Confirm disabled integrations from runtime configuration and logs.

## E. Seven-year retention baseline and deletion evidence

Map the stated **seven years** to each system record class. The owner must decide and document the start trigger, applicable exception, legal hold, backup expiry, restore behavior and service-exit process. If a record class needs a different rule, record the rationale and approved period rather than applying seven years mechanically.

| Record class | Seven-year period starts from | Legal/contractual rule and exceptions | Purge/return method for primary and attachments | Backup/export expiry and restore reconciliation | Test/evidence/owner |
|---|---|---|---|---|---|
| Patient profile, prescription, dispense, clinical encounter and attachment | `[OPEN per class]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Practitioner credentials and verification evidence | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Customer and staff accounts, roles, sessions and access events | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Sales, payments, refunds, invoices, stock and claims | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Audit, support, security and incident logs | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Backups, extracts, exports and support copies | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` | `[OPEN]` |

Attach an implementation or operations test showing deletion/return across the database, clinical objects, exports, replicas and backups, including what happens if an old backup is restored. The current repository evidence does not establish that lifecycle.

## F. Safeguard and availability evidence

Attach evidence for the exact live release/environment; source-code behavior and policy drafts alone do not establish production operation.

| Control | Evidence required | Status / owner |
|---|---|---|
| Tenant isolation and role/capability checks | Release-specific tests, denial monitoring, privileged-access inventory/review | `[OPEN]` |
| Privileged authentication and device lifecycle | MFA evidence or approved compensating control; joiner/mover/leaver and lost-device revocation test | `[OPEN]` |
| Encryption in transit and at rest | Live TLS/database/storage/backup configuration and key custody/rotation evidence | `[OPEN]` |
| Clinical attachment protection | Active application keyring and legacy migration evidence; host/volume encryption proof; scanner status/test; authorization and access audit | `[PARTIAL — live object keyring valid; no stored objects at audit; host/DB at-rest, key custody/rotation and deferred scanner remain OPEN]` |
| Audit, monitoring and support access | Event coverage, remote protection/retention, named support access and review evidence | `[OPEN]` |
| Backup, restore and continuity | Backup schedule/locations/retention, full restore exercise, approved RTO/RPO and owner | `[OPEN]` |
| Incident response | Named contacts, processor-to-controller escalation, tabletop record and lessons closed | `[OPEN]` |
| Independent vulnerability/security assessment | Scope, dated report, findings, remediation and retest; do not relabel CI scan as penetration test | `[OPEN]` |
| Staff security/privacy training | Current training and endpoint management/patching evidence | `[OPEN]` |

## G. Health-sector and regulatory readiness

| System-level requirement | Evidence / owner / status |
|---|---|
| ODPC registration for the TibaTrace owner/operator in each applicable role | `[OPEN]` |
| DHA applicability/classification, certification application/certificate and go-live status | `[OPEN — no certificate found in repository evidence reviewed]` |
| System-level health reporting and interoperability profile, if enabled | `[OPEN; mark future specifications as not connected]` |
| Product privacy/security, backup/recovery and cyber-assessment documents required for DHA submission | `[OPEN — map to current DHA evidence checklist]` |
| New health-data exchange approval, recipient agreements, production credentials and tests | `[OPEN per interface; none should be enabled without approval]` |

Customer facility licenses, clinical purposes and controller lawful bases are outside this system-provider DPIA; each customer remains responsible for its own regulatory duties and controller assessment.

## H. Consultation and approval

| Stakeholder | Name/role | Date/method | Feedback and change to assessment |
|---|---|---|---|
| TibaTrace service/system owner | Esenai Group Ltd / Sidney Chepkwony (owner-nominated approver) | 25 October 2026 / chat declarations | Identity/contact supplied; Kenya hosting correction recorded; consultation/sign-off incomplete |
| System DPO/privacy lead or appointment reviewer | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Clinical/pharmacy product lead | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Security/operations lead | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Representative customer/user | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Patient/community representative, where appropriate | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Legal reviewer | `[OPEN]` | `[OPEN]` | `[OPEN]` |

| Accountable system sign-off | Name/legal entity | Decision and residual-risk treatment | Signature/date |
|---|---|---|---|
| System owner/provider representative | Esenai Group Ltd / Sidney Chepkwony | Pending residual-risk review | Pending |
| System DPO/privacy lead | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Security/operations owner | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Clinical/product owner | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Legal reviewer | `[OPEN]` | `[OPEN]` | `[OPEN]` |
| Data Commissioner consultation, if required | `[Reference/outcome or not applicable with reason]` | `[OPEN]` | `[OPEN]` |

Approval gate: the system owner's legal identity and roles are confirmed; product purposes and scale envelope are described; every production flow/provider/location is inventoried; the seven-year baseline is mapped to record classes and implemented/tested; security and recovery evidence is attached; health-sector applicability/certification is established; consultation is recorded; residual risks have owners and a signed decision. A customer-specific DPIA is a separate controller deliverable and is not a substitute for this system-owner approval.
