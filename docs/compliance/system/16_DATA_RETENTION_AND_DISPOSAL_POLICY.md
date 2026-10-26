# TibaTrace Data Retention and Disposal Policy — Draft

**Status:** Draft; system owner has stated a seven-year baseline, but record-class triggers and implementation evidence remain open  
**Policy owners:** Tenant data controller and Esenai service owner  
**Review:** Before production adoption, at least annually, and when health-record law or system purpose changes

## 1. Rule

Keep personal data only as long as needed for its documented purpose, applicable legal/clinical record duty, safety need, dispute, audit, or valid legal hold. Then securely erase, anonymize, or return it in accordance with the controller/processor agreement. Do not delete a record just because a user asks if another law requires retention; assess the request and explain the decision.

The TibaTrace system owner has provided a **seven-year retention baseline**. This is recorded as the product owner's current policy direction, not as independent legal validation that one duration is appropriate for every record class. Before adoption, the owner must define when the seven years starts for each class, document any statutory/contractual exception or different period, and obtain legal/DPO approval. Apply the schedule to each relevant system record only after the trigger, hold, backup and purge behavior is specified.

Kenya's Data Protection Act and General Regulations require purpose limitation and retention governance. Regulation 19 requires personal data to be retained only as long as necessary for its purpose and calls for retention schedules with appropriate periodic review time limits. This document does not establish that seven years is the correct period for every record class. The controller and system owner must obtain legal advice for pharmacy, clinical, finance, tax, employment, controlled-medicine and litigation records. The schedule below keeps class-specific start triggers and exceptions open rather than inventing them.

## 2. Schedule to approve

| Record class | Examples | Retention owner | Seven-year baseline: start trigger / exceptions to approve | Disposal method |
|---|---|---|---|---|
| Patient clinical record | Patient profile, prescription, allergies, clinical encounter, dispense | Tenant controller / processor per agreement | `[7 years; start event and child/clinical exceptions OPEN]` | Controlled record deletion/anonymization after hold check; remove linked attachments and derived exports |
| Patient identity material | Encrypted national/other identifier, lookup digest, evidence | Tenant controller / processor per agreement | `[7 years or shorter if no longer required; start event OPEN]` | Crypto-safe deletion/re-key strategy plus linked digest/backup lifecycle |
| Practitioner credentials | Licence claims, verification evidence, controlled-medicine authority | Tenant/controller and system owner by role | `[7 years; expiry/renewal trigger and legal exception OPEN]` | Securely dispose after expiry plus required dispute/regulatory period |
| Financial/payment | Sale, payment reference, refund, till ledger, tax invoice | Tenant controller / processor per agreement | `[7 years; transaction/accounting trigger OPEN]` | Preserve required ledgers; remove secrets/card data not needed; dispose securely |
| Stock/regulatory traceability | Batch, receipt, recall, quarantine, release, controlled inventory | Tenant controller / processor per agreement | `[7 years; batch/recall trigger and legal exception OPEN]` | Preserve traceable decision history for approved period |
| User/access/audit | User profile, role grant, auth, audit event, document access | Relevant controller/vendor by role | `[7 years baseline; last activity/event trigger and security exceptions OPEN]` | Controlled expiry; keep only required audit metadata; prevent casual alteration |
| Documents/attachments | Uploaded prescription or clinical attachment | Tenant controller / processor per agreement | `[Follow associated record class; trigger OPEN]` | Delete object and index/backup copy under documented lifecycle |
| Support/security logs | Proxy, application, host and incident logs | Esenai service owner | `[7 years baseline stated; event/incident trigger and minimization review OPEN]` | Restricted automated expiry after required hold and investigation |
| Backups and exports | DB backups, object snapshots, CSV/PDF exports | Esenai/tenant by custody | `[Seven-year records may be present in backups; backup expiry/restore trigger OPEN]` | Expire encrypted copies; securely destroy keys/media; verify disposition |
| Demo/test data | Synthetic test and training records | Data owner | `[Do not apply seven years by default; short exercise-specific period to approve]` | Delete/reset; never mix with live patient records |

## 3. Data subject requests and legal holds

Route access, correction, objection, restriction, portability and deletion requests to the controller. Verify identity and authority, identify all tenant copies/attachments/exports, record the response, and apply applicable exceptions. Apply legal, regulatory, litigation, complaint and incident holds before disposal. A hold must identify scope, owner, reason, start date, review date and release authority.

## 4. Technical disposal requirements

- Deletion must cover primary records, attachment objects, search/cache copies, derived exports and accessible replicas, subject to backups and legal holds.
- Backups expire under their own documented lifecycle; restoration must reapply deletions/holds recorded after the backup point before data is returned to users.
- Retain minimum non-identifying evidence of disposition: record class, tenant, count, execution time, authorized actor/job, method and outcome.
- Do not overwrite immutable audit events to satisfy an ordinary deletion; remove personal identifiers from audit metadata where possible and document lawful retention.
- For cryptographic erasure, confirm no recoverable copy remains under another key or backup.
- Reconcile disposal jobs and surface failures; a failed purge remains an open compliance incident/task.

## 5. Implementation status

The system owner has stated a seven-year baseline, but the reviewed code and release records do not establish a signed record-class schedule, configurable expiry service, completed service-exit purge, or recurring deletion evidence. This policy must not be marked operational until the system owner approves triggers and exceptions, engineering maps them to records, and a test proves primary/attachment/backup lifecycle behavior.

## 6. Legal references

- [Data Protection Act, 2019](https://new.kenyalaw.org/akn/ke/act/2019/24/eng@2019-11-15/source)
- [Data Protection (General) Regulations, 2021](https://www.odpc.go.ke/wp-content/uploads/2024/03/THE-DATA-PROTECTION-GENERAL-REGULATIONS-2021-1.pdf), including regulation 19 on retention
- [ODPC data protection guidance](https://www.odpc.go.ke/guidelines-2/)
