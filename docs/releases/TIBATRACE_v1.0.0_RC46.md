# TibaTrace 1.0.0-rc46

Status: deployed and verified on 14 October 2026; see the
[activation and live permission checks](RC46_RELEASE_VERIFICATION_2026-10-14.md).

Targeted HQ tenant-navigation isolation; see
[scope and verification](RC46_TENANT_NAVIGATION_ISOLATION.md).

Owner-only functions are hidden from tenants across sidebar, search, shortcuts,
account menu, regulator-alert register and hash routes. Tenant workflows and
recall response remain available according to existing server-side permissions.
Explicit owner API guards stay enforced. Owners retain global tools inside a
selected tenant.

Supersedes undeployed rc45. No model migration, role mutation, data seeding or
native installer change. Retain rc44 application images/source and a fresh
root-only database backup for rollback. Candidate is not live until all release
gates and activation checks pass.
