# rc46 — tenant navigation isolation

Status: candidate; not deployed until final-source gates and live verification
pass. Supersedes the undeployed rc45 candidate; rc44 is the rollback target.

Includes the sidebar, mobile navigation, search, shortcuts, notification/account
links, legacy shell and pre-mount hash guards described in
[the navigation scope](RC45_TENANT_NAVIGATION_ISOLATION.md). Explicit active
platform-admin/superuser identity is required for Executive Dashboard, Pharmacy
network, National Integrations, Platform Owner Console and global telemetry.
Tenant wildcard roles and tenant scope labels never imply platform ownership.
Existing owner-only API guards remain enforced; no role or access grant changes.

Tenant workflows follow fresh effective capability grants. Tenant user/access
administration and audit/documents remain tenant-labelled, not global controls.
Owners retain global tools while operating inside a selected tenant.

Recall navigation is aligned with `RecallTenantPermission`: recalls.read,
recalls.manage, compliance.officer, inventory.read or inventory.manage grant
access to the tenant response queue. Practitioner-only permission does not.
The inner global regulator-alert tab and intake/activation controls are hidden
from tenants and are not fetched. Owners retain that register inside a selected
tenant. Both tenant recall isolation and the owner-only global recall API are
covered by additional regressions.

No model migration, trading-data write, credential reset, live access grant or
native POS source change. Signed managed Windows 1.0.5 remains unchanged;
Android signing, provider onboarding and Manager stock/hardware acceptance are
still separate pending checks. Untracked prototypes and user documents remain
preserved and excluded.

Local verification: 102 migrated SQLite navigation/session/HQ/identity/pharmacy/
security tests passed, including the actual recall API permission matrix and
global recall refusals. HQ's 82 DOM/API tests passed, including three regulator
register/revocation tests; shared/Windows/Android remain 211/106/41 passed (440
total client/shared tests). All application types/builds passed, and HQ was
rechecked after the recall changes. Ruff and diff whitespace checks passed.

Final-source Production Images validation must still run the full migrated
SQLite and PostgreSQL 16 business suites, clean-checkout Node gates, strict
dependency audit, high/critical image scans and immutable image evidence before
activation. No CI gate is bypassed.
