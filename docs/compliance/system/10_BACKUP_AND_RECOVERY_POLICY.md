# TibaTrace Backup and Recovery Policy — Draft

**Status:** Operating policy draft; service owner approval and job evidence required  
**Policy owner:** Esenai infrastructure owner (to assign)  
**Systems:** PostgreSQL, clinical object volume, release/configuration metadata, audit and integration configuration

## 1. Policy

Backups must allow authorized recovery of the system and its records after human error, infrastructure failure, ransomware, release failure or data corruption. A successful backup command is not proof of recoverability. Backup copies must be encrypted, access controlled, separated from routine application credentials, integrity checked and periodically restored in an isolated environment.

## 2. Protected data and order of recovery

| Priority | Data | Recovery treatment |
|---|---|---|
| 1 | PostgreSQL production database | Consistent encrypted backup; include WAL/PITR where configured; record schema/release compatibility |
| 2 | `clinical-objects` attachment volume | Encrypted copy coordinated with database snapshot; verify content hashes and tenant paths |
| 3 | Production configuration and secret references | Recover from approved secret manager; never store plaintext secrets in ordinary backup artifacts or tickets |
| 4 | Release manifest, image digests, migrations, Caddy configuration | Preserve exact versioned release material and validate provenance/checksums |
| 5 | Redis state | Rebuildable cache/broker/results; preserve persistence when useful, but do not treat Redis as a system of record |

## 3. Minimum operational schedule to approve

The production owner must fill and approve these values before calling the policy operational:

| Control | Required value/evidence |
|---|---|
| Database backup frequency | `[schedule; proposed minimum: daily full backup, plus WAL/PITR where operationally supported]` |
| Clinical object backup frequency | `[schedule; consistent with database recovery point]` |
| Backup retention | `[daily/weekly/monthly periods approved against the data-retention schedule]` |
| Off-host or separate-failure-domain copy | `[provider/location and access owner]` |
| Encryption and key custody | `[algorithm/service, key owner, rotation and recovery route]` |
| RPO / RTO | `[approved values linked to Disaster Recovery Plan]` |
| Restore exercise | `[frequency, environment, evidence location, approver]` |

Every production schema-changing release must have a verified pre-deployment backup and a documented rollback/recovery decision. The rc52 release record documents a release-specific PostgreSQL backup and checksum/restore-inventory checks. It does not prove the recurring schedule above, a complete database-plus-object restore, or an approved retention SLA.

## 4. Backup security

- Encrypt backup data in transit and at rest using managed encryption keys separated from the host/application secret.
- Limit backup/restore privileges to named operators; log access, downloads, deletion and restore actions.
- Prevent ordinary application containers and tenant users from listing or deleting backups.
- Keep at least one protected copy outside the primary host/failure domain; verify the provider's location, data residency and subprocessors.
- Test credentials and key recovery without exposing secrets. Do not place keys in the same unprotected backup as the encrypted data.
- Apply malware/ransomware protections and immutable retention where available.
- Dispose of expired copies using approved secure deletion and verify lifecycle completion.

## 5. Recovery procedure

1. Declare the recovery event and identify affected tenant(s), data types, last known-good time and possible compromise. Preserve original media/logs.
2. Select a clean recovery environment and trusted release digest. If compromise is suspected, rotate access material and do not reconnect compromised hosts.
3. Restore PostgreSQL to a new isolated database; validate database integrity, migrations, tenant counts and critical ledgers without modifying the original evidence.
4. Restore the matching clinical-object snapshot. Verify file count, tenant directory structure, stored size and SHA-256 values against metadata.
5. Restore approved configuration and secrets from the secret manager; validate TLS, hostnames, permissions and provider disabled/active states.
6. Start API, worker, beat and HQ against the restored data. Validate health, login, tenant isolation, required workflows, asynchronous queues, documents, audit and payment/stock reconciliation.
7. Obtain security owner, database owner and affected clinical/tenant owner approval before switching traffic. Maintain the prior state for evidence and rollback.
8. Record the recovery point, elapsed times, data loss, validation results, authorizations, incidents and corrective actions.

## 6. Recovery tests

At least quarterly, restore a representative database and object set into an isolated environment. At least annually, test a full service recovery from a separate failure domain. Tests must not use public production endpoints or send live provider notifications. Retain logs, hashes, restore times and independent reviewer sign-off.
