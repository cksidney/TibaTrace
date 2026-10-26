# TibaTrace Access Control Policy — Draft

**Status:** Draft for service-owner/controller approval  
**Applies to:** HQ, Windows/Android POS, APIs, database/admin access, backups, CI/CD and provider credentials

**Production evidence note, 26 October 2026:** the rc71 review did not find in-application privileged MFA. MFA enrollment/recovery/revocation and recurring access/device reviews remain closure items; this draft is not evidence that they are active.

## 1. Principles

- Every human has a unique account; every service has a named service identity.
- Access is deny-by-default, least privilege, time-bounded where practical, and limited to the authorized tenant, branch, device and purpose.
- UI visibility is only navigation. The API and data layer make the authorization decision.
- Platform-owner authority is explicit and separate from tenant roles. Wildcard tenant capability does not create platform-owner status.
- Separate request, approval, execution and reconciliation duties for sensitive clinical, financial, inventory, access and release actions.
- Access and privilege changes are auditable; high-risk permissions are reviewed routinely.

## 2. Access lifecycle

### Joiner

1. Manager verifies identity, employment/contract, role and tenant/branch need.
2. Create named account, assign minimum role/capabilities and required training.
3. Issue temporary credentials through a secure channel; require password replacement at first sign-in where supported.
4. For POS, register device and operator identity using approved activation and challenge procedures.
5. Record requester, approver, grant, scope and date.

### Mover

Reassess and remove old permissions before granting new role scope. Record approval and retain required history. Do not copy another employee's role blindly.

### Leaver or suspension

Disable account and sessions promptly; revoke POS device/session and service credentials; remove group/role assignments; recover devices; transfer records under manager approval; preserve records subject to retention/legal hold. Record completion and verification.

## 3. Role separation

| Role | Normal scope | Prohibited by default |
|---|---|---|
| Cashier | Register, retail basket/payment, shift and receipt tasks for assigned branch | Patient identity reveal, pharmacist decisions, clinical override, tenant/platform access administration |
| Pharmacist | Prescription review, clinical checks, authorized dispensing/counselling | Platform-wide administration, unrelated tenant access, self-approval where independent reviewer is required |
| Inventory/receiving | Catalogue/stock receiving, batch, transfer and stocktake tasks | Clinical authorization, payment settlement, platform-owner operations |
| Tenant manager/admin | Own tenant users, branch/workflow configuration and authorized reports | Other tenant records or platform-owner-only functions |
| Platform owner | Global operations specifically assigned to the platform-owner identity | Routine tenant clinical access without documented support/operational need |
| Service identity | Narrow, non-interactive API/job capability | Interactive login, wildcard authority, unscoped tenant reads |

The capability catalogue and workflow-level RBAC matrices are authoritative for exact grants. This table is an illustrative baseline, not an automatic grant list.

## 4. Privileged access

- Limit platform owners, production shell/SSH, database superusers, backup key holders, CI signing and secret-manager administrators to named individuals.
- Require MFA on privileged accounts where supported and separate privileged/admin identities from routine accounts.
- Use approved break-glass access only for emergency, record reason and scope, notify the owner, and review immediately afterward.
- Review platform owners, tenant managers, sensitive patient-data roles, database and backup access at least quarterly and at each tenant exit.
- No shared root or personal account credentials. Secrets must not be pasted into repository, chat, or support tickets.

## 5. Authentication and session controls

Use the configured HQ session/CSRF flow and native POS token/device flows. Protect passwords, PINs, tokens, session cookies and recovery channels. Revoke sessions after suspected compromise, role termination or device loss. Authentication rate limits and device/session checks must be maintained by the release process. No in-application privileged MFA was found in the reviewed rc71 production boundary; do not claim it is enabled until its enrollment, challenge, recovery and revocation paths are verified.

## 6. Monitoring and violations

Review failed sign-in spikes, cross-tenant denials, sensitive identity reveal, privilege changes, unusual exports, device activation/revocation and privileged platform actions. Investigate access outside assigned scope under the Incident Response Plan. Violations may result in access suspension and formal incident response.

## 7. Exceptions and review

Exceptions require documented purpose, tenant/data scope, expiry, compensating controls, accountable approver and audit event. Never approve an exception that violates applicable law or makes tenant boundaries optional. Review this policy annually and after material access-model changes.
