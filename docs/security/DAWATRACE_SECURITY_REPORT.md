# DawaTrace Phase 2 Security Report

## Scope and Decision

This report covers the extracted clinical core, not production infrastructure or
clinical-content efficacy. Local controls passed, but external advisory and
container vulnerability intelligence remain release gates. Phase 2 is therefore
not a production security certification.

## Executed Results

| Control | Result |
| --- | --- |
| Django production-template deployment check | 0 issues |
| Bandit 1.8.3 | 0 findings across 10,708 lines |
| Local secret scan | 0 findings |
| Unsafe healthcare/FHIR UUID lookup audit | 0 findings |
| Tenant-manager audit | 54 tenant-bearing models, 0 unreviewed findings |
| Tenant ownership audit | safe to enforce; 0 null-tenant rows or relation mismatches |
| Backend security/tenant tests | 32 passed |
| `pip check` | no broken requirements |

The one documented manager exception is `identity.User`. Authentication must find
a user before tenant middleware can establish context; role/capability checks and
all healthcare access remain tenant-qualified. This exception is explicit and is
covered by authentication and tenant-isolation tests.

## Tenant and Authorization Controls

- Tenant-bearing healthcare models use fail-closed managers or an explicit
  tenant/global manager for approved CDS and terminology fallback.
- UUID scans reject direct unscoped healthcare and FHIR lookups.
- Cross-tenant read/write, identity mapping, reference resolution, document
  download, workflow job, notification job, audit, and FHIR paths are tested.
- Background jobs require an explicit tenant and audit denied cross-tenant work.
- Audit events and crosswalks are immutable through application behavior.
- Cashier-like users cannot perform clinical review or CDS override without the
  required capability; deny policies take precedence over grants.

## Document Security

Document object keys include the tenant, and access tokens bind tenant, actor,
capability, and expiry. Uploads enforce content type, extension, size, metadata,
and SHA-256 validation. Reads verify the stored hash and audit success/failure.
Phase 2 includes a malware-scanner integration point but no live scanner or
external object-storage adapter.

## Outstanding Gates

The local environment did not transmit dependency or image metadata to external
advisory services. `pip-audit`, `npm audit`, and a current container/OS CVE scan
must run in an approved trusted environment before release. The tracked CI
workflow contains Python and npm advisory gates plus a visible container-scan
gate; the latter must be replaced with the organization's approved scanner.

Secret scanning is a source-tree regex baseline and does not replace full Git
history, entropy, and credential-validity scanning. PostgreSQL authorization,
Redis ACL/TLS, object-store IAM, key rotation, backup/restore, penetration tests,
and production threat-model review remain outside Phase 2.

## Evidence

Evidence is under `artifacts/evidence/security/`, including Bandit, CycloneDX,
secret, UUID, manager, tenant-ownership, deployment-check, installed-package, and
dependency-audit status records.
