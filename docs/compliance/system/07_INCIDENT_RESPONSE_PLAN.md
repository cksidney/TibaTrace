# TibaTrace Incident Response Plan

**Status:** Operational draft; activate after naming responders and verifying contact routes  
**Plan owner:** Esenai security lead (to assign)  
**Applies to:** Hosted service, tenant users/devices, clinical documents, backups, integrations and release pipeline

## 1. Response objectives

Protect patients and users, stop unauthorized access or unsafe processing, preserve reliable evidence, restore safe service, and meet controller/processor and regulatory notification duties. A technical outage is not automatically a personal-data breach; classify both security impact and service/clinical impact.

## 2. Events to report immediately

- Suspected patient or tenant data disclosure, cross-tenant access, or unauthorized account use.
- Lost or stolen POS device, admin workstation, credential or backup medium.
- Ransomware, malware, suspicious code, unexpected privileged changes, or service compromise.
- Missing/altered prescription, payment, audit, inventory or document records.
- Failed backup, suspected backup compromise, or inability to restore needed clinical records.
- Unauthorized provider callback, integration credential exposure, or regulator feed tampering.
- Outage or integrity issue that could affect safe dispensing, recall response, or continuity of care.

**Report to:** `[24/7 incident channel and phone to be assigned]`  
**Tenant escalation:** `[tenant manager/privacy contact]`  
**Esenai incident lead:** `[name/phone/email]`  
**Data Protection Officer:** `[name/phone/email]`

## 3. Severity and escalation

| Level | Example | Initial response |
|---|---|---|
| SEV-1 Critical | Confirmed broad health-data disclosure, active cross-tenant compromise, ransomware affecting production, or unsafe clinical integrity | Incident lead and executive/DPO immediately; isolate affected services/accounts; notify affected tenant controllers without delay |
| SEV-2 High | Confirmed single-tenant exposure, privileged credential misuse, material data corruption, or outage affecting care/dispensing | Security and tenant leads promptly; contain and assess scope; provide frequent updates |
| SEV-3 Moderate | Limited suspicious access or a contained vulnerability without confirmed data exposure | Triage during same business day; preserve evidence, patch/monitor, document decision |
| SEV-4 Low | Benign alert or user-reported issue with no evidence of compromise | Record, validate and close through normal support process |

If severity is uncertain, start at the higher plausible level until evidence narrows it.

## 4. Response phases

### A. Detect and record

Open an incident record with unique ID, reporter, first-known time, discovery time, systems/tenants affected, data types, current impact, and correlation/request IDs. Preserve original evidence and record who handled it.

### B. Contain

- Revoke or rotate compromised credentials/tokens through approved operations.
- Restrict the affected user, device, endpoint, integration or service; preserve enough evidence to investigate.
- Isolate compromised hosts/containers or disable an unsafe integration. Do not destroy disks, logs, database rows or backups.
- Pause unsafe clinical/payment workflows and inform the tenant manager when record integrity is uncertain.

### C. Assess and notify

Determine whether personal data was accessed/acquired by an unauthorized person, the affected subjects and records, likely harm, exposure window, data protection measures, recipient and country, and whether the data remain accessible. Record known facts and uncertainties.

Under section 43 of Kenya's Data Protection Act, a controller must notify the Data Commissioner without delay and within 72 hours of awareness where unauthorized access/acquisition creates a real risk of harm; if late, reasons are required. The controller communicates with affected data subjects within a reasonably practical period subject to statutory exceptions. A processor must notify the controller without delay and, where reasonably practicable, within 48 hours. The DPO/legal lead must confirm applicability and execute the notification; this plan does not replace legal advice.

### D. Eradicate and recover

Remove the cause, patch or rebuild from trusted images, restore only from verified clean backups, rotate exposed secrets/keys with an approved migration plan, and verify tenant scope, clinical/payment integrity, migrations and background jobs. Obtain accountable clinical/tenant approval before resuming affected workflows.

### E. Close and learn

Record timeline, scope, root cause, legal decisions and notices, evidence hashes, containment/recovery steps, costs, corrective actions, owners and due dates. Conduct a no-blame review and update DPIA, access controls, runbooks, training and tests.

## 5. Evidence handling

Keep access-controlled copies of relevant application/security logs, request IDs, image digests, host/container metadata, provider messages, database snapshots and screenshots. Preserve timestamps and hashes. Avoid collecting extra patient content; redact it from routine incident channels. Never include passwords, tokens, private keys or live patient data in a ticket or chat.

## 6. Communications

Only the incident lead or authorized controller representative sends external communications. Messages should state verified facts, affected dates/data, steps users should take, contact route and next update. Do not speculate about cause or scope.

## 7. Exercises and readiness

Run a tabletop exercise at least annually and after major architecture change. Exercise at minimum: lost POS device, cross-tenant disclosure, ransomware/backup recovery, and provider callback compromise. Record actual timing, notification decisions, evidence gaps and remedial owners. Exercise evidence is not present in this document set; schedule and retain it separately.
