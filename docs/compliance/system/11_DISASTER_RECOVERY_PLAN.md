# TibaTrace Disaster Recovery Plan — Draft

**Status:** Plan draft; RTO/RPO, contacts, and exercise evidence outstanding  
**Plan owner:** Esenai service owner (to assign)  
**Last reviewed:** 17 October 2026

## 1. Purpose and recovery objective

Restore TibaTrace safely after an event that makes the primary host, network, database, object volume, deployment credentials or release pipeline unavailable or untrustworthy. Protect patient safety and record integrity first. Do not restore traffic until security and business owners agree that the recovered service is safe.

**Approved RTO:** `[owner decision required]`  
**Approved RPO:** `[owner decision required]`  
Until approved, no guaranteed recovery time or data-loss window is promised.

## 2. Recovery leadership

| Responsibility | Named primary / alternate |
|---|---|
| Incident commander / executive decision | `[name, 24/7 contact]` |
| Infrastructure and deployment | `[name, contact]` |
| Database and backup custodian | `[name, contact]` |
| Security and evidence | `[name, contact]` |
| DPO/privacy notification | `[name, contact]` |
| Clinical safety/pharmacy lead | `[name, contact]` |
| Tenant communications | `[name, contact]` |
| Hosting/provider support | `[provider account and support route]` |

## 3. Activation criteria

Activate for prolonged outage, lost or corrupted database, unavailable clinical-object volume, ransomware or host compromise, fire/flood/physical loss, failed release with unsafe data state, compromised signing/secrets systems, or a regional network/cloud failure that prevents safe service.

The incident commander declares the plan, records time/severity, appoints a scribe, sets a secure communication channel and decides whether tenant workflows need to stop or use an approved paper-continuity procedure.

## 4. Recovery strategy

1. **Stabilize and assess:** isolate suspected compromised resources; determine which data and hosts remain trustworthy.
2. **Provision clean capacity:** use a hardened replacement host/network and approved DNS/TLS procedure. Restrict access to recovery operators.
3. **Recover data:** follow the Backup and Recovery Policy, restoring the latest verified consistent PostgreSQL and clinical-object set. Verify tenant ownership, hashes and critical workflow ledgers.
4. **Recover service:** deploy exact trusted backend/HQ digests and compatible migrations. Configure PostgreSQL TLS, Redis isolation, HTTPS, monitoring, backups and malware scanning.
5. **Validate:** test health, sign-in, tenant access boundaries, clinical/retail workflow integrity, document access, reports, audit events, job queue, restore-time data gaps and payment/stock reconciliation.
6. **Return to service:** owner, security, database and clinical lead sign off. Communicate current limitations and recovery point to tenants.
7. **Follow up:** reconcile queued and offline work; assess breach notification; preserve old infrastructure for forensics; complete lessons learned and corrective actions.

## 5. Scenario runbooks

| Scenario | Immediate action | Recovery route |
|---|---|---|
| Host compromise/ransomware | Disconnect/isolate host; revoke deploy and backup credentials; preserve forensic image | Rebuild clean host, rotate secrets safely, restore clean database/object copies, validate before DNS cutover |
| PostgreSQL loss/corruption | Stop writes if needed; preserve logs and failed storage | Restore to isolated database/PITR point, validate records and migrations, then switch application |
| Object-volume loss | Disable affected document workflows; do not recreate missing content as empty files | Restore matching attachment copy; verify stored hash/size and document-access audit consistency |
| Bad software release | Route traffic to prior known-good compatible release; inspect migration reversibility | Roll back application digest; if data was altered, follow controlled point-in-time recovery and business reconciliation |
| Secret or signing-key compromise | Disable affected credentials/integration; preserve evidence | Reissue keys and tokens, assess encrypted data readability, perform planned re-encryption where needed |
| Extended regional/network outage | Invoke tenant continuity process and advise users not to assume queued payments/stock are settled | Restore network/service; reconcile delayed events using authoritative source evidence |

## 6. Dependencies and communications

Maintain current DNS/domain ownership, TLS renewal route, hosting support, image registry access, secret-manager access, database recovery credentials, backup keys, approved release digests, tenant escalation contacts, manual continuity forms and regulator contacts. Store a protected copy of this plan and contact tree outside the primary host.

Communications must distinguish known from unknown facts. The DPO/controller applies the breach-notification process and legal time limits; restoration and privacy response run in parallel.

## 7. Exercises and maintenance

Exercise this plan annually and after material hosting/database changes. At minimum, perform a tabletop for host loss and a technical restore including clinical objects. Record measured RTO/RPO, data integrity, missed dependencies, decisions and corrective actions. No completed DR exercise was evidenced in the source material reviewed for this draft.
