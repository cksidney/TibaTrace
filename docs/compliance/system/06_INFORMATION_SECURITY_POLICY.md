<!-- TIBATRACE DOCUMENT BRANDING START -->
<p><img src="../brand/tibatrace-logo.jpeg" alt="TibaTrace logo" width="150"> &nbsp; <img src="../brand/esenai-group-logo.png" alt="Esenai Group logo" width="200"></p>

**TibaTrace · Esenai Group Ltd**<br>
Branding edition: 26 October 2026. Assessment dates, evidence scope and approval decisions below remain controlling.
<!-- TIBATRACE DOCUMENT BRANDING END -->

# TibaTrace Information Security Policy — Draft

**Status:** Draft for adoption by Esenai service owner and tenant controllers; reviewed against rc71 evidence on 26 October 2026<br>
**Policy owner:** Esenai Group Ltd security lead (name to assign)  
**Review cadence:** At least annually and after a material incident or architecture change

## 1. Purpose and scope

This policy protects the confidentiality, integrity and availability of TibaTrace information and services, including patient and practitioner information, tenant business records, software, endpoints, credentials, backups and production infrastructure. It applies to Esenai personnel, tenant administrators and users, contractors, and approved subprocessors who access the system.

The tenant controller remains responsible for its own lawful purposes, staff, endpoint security, user approvals and operational records. Esenai is responsible for the hosted service controls it operates under the service agreement. The contract and data-processing agreement determine specific responsibilities.

## 2. Security principles

1. Grant the least access needed for a named job; use tenant and branch scope.
2. Keep platform-owner privileges explicit, limited and separately reviewed.
3. Protect health data in transit and at rest. Newly stored clinical objects use the versioned application encryption keyring described in the encryption specification; provision, rotate and recover keys under named operational control. Also encrypt the host volume and backups. Do not treat application encryption as a substitute for database/volume/backup protection.
4. Keep secrets out of source code, tickets, chat, and application data fields. Use the approved secret-management channel.
5. Record security-relevant and clinical/business actions with actor, tenant, time, object and outcome where supported. Do not put unnecessary health data in logs.
6. Ship only reviewed, immutable release artifacts with vulnerability and provenance evidence.
7. Test backups and restore, not just backup-file creation.
8. Report suspected compromise promptly and preserve evidence.
9. Disable unconfigured external integrations and fail closed on unverified information.
10. Retain and dispose of records under an approved schedule and legal hold.

## 3. Required controls

### Identity and access

- Individual accounts; no shared administrator account.
- Capability-based access and tenant scoping; deny policies take precedence.
- Prompt access removal when employment, role, contract or device authorization ends.
- Periodic review of privileged and sensitive-data access; record owner, date and result.
- Strong unique passwords and secure device/PIN handling. Require MFA for privileged access wherever available and document compensating controls if not available.

### Infrastructure and application

- Production HTTPS, secure cookies and hardened HTTP headers.
- PostgreSQL TLS, isolated service credentials and restricted network exposure.
- Redis restricted to the TibaTrace service boundary and protected with credentials.
- Production secrets held outside the repository and release artifact.
- Tenant-aware authorization and validation in the API; UI hiding is not an authorization control.
- Approved malware scanner required for clinical uploads in production.
- Separate backup access from routine application access; encrypt backups and verify integrity.

### Development and release

- Review changes affecting identity, tenancy, health workflows, audit, payment, encryption or retention.
- Run the release gates required by the release workflow, including tests, dependency/image scanning, checksums and provenance.
- Use immutable image digests and preserve the previous known-good release for rollback.
- Do not use real patient or payment data for test fixtures unless explicitly authorized and protected.
- Log and remediate vulnerabilities by severity and exposure; document accepted risk and expiry.

### Physical, endpoint and personnel security

- Secure server, workstation and till access; apply supported OS updates and endpoint protection.
- Encrypt managed laptops and removable backup media.
- Protect printer output and printed labels/receipts from unauthorized collection.
- Train authorized users on confidentiality, phishing, incident reporting and safe dispensing records.

## 4. Security events and non-compliance

Report suspected credential exposure, cross-tenant access, lost devices, malware, data exfiltration, unauthorized modification, backup failure, or unsafe release to the designated incident contact immediately. Preserve logs and records; do not delete or alter evidence. The incident lead classifies, contains and escalates under the Incident Response Plan.

## 5. Exceptions and approvals

An exception must name the risk, affected system/data, compensating controls, accountable owner, expiry date and approval. No exception may waive a legal duty or permit cross-tenant disclosure.

## 6. Measures and review evidence

Keep current evidence for: access reviews, privileged accounts, security scans, patch actions, release approvals, backup jobs and restore tests, incident exercises, third-party contracts, endpoint status, security training and approved exceptions. The rc71 release record is point-in-time evidence only; it does not replace recurring controls. Privileged MFA, malware scanning, host/database at-rest protection and separate key custody remain open in the reviewed production boundary.

## 7. Approval

| Approver | Name | Signature/date |
|---|---|---|
| Esenai executive/service owner | To assign | Pending |
| Security lead | To assign | Pending |
| Tenant controller representative | Per tenant | Pending |
| Data Protection Officer | To name | Pending |
