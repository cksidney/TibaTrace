# rc45 — tenant navigation isolation

Status: withdrawn before deployment. Its release run was cancelled to align
recall-menu grants with the actual tenant API and hide the inner global-alert
tab. No rc45 image was activated. The immutable tag is retained as history;
[rc46](RC46_TENANT_NAVIGATION_ISOLATION.md) supersedes this candidate. rc44 stays
live until the replacement passes its final-source gates and activation.

HQ navigation previously rendered every module for every authenticated user.
This release uses fresh server-side effective capabilities for tenant menus
and explicit active platform-admin/superuser identity for owner-only menus.
Tenant roles, wildcard permissions, scope labels and selected workspaces never
confer platform ownership. No role or access grant is changed by this release.

Owner-only destinations: Executive Dashboard, Pharmacy network, National
Integrations and Platform Owner Console. Platform telemetry and API-documentation
shortcuts are also absent from tenant navigation. API documentation itself is
not claimed to be a protected business-data endpoint.

Tenant workflows remain available according to existing grants, including
inventory, catalogue, procurement, commerce, pricing, clinical, insurance,
reports, practitioner/recall governance and tenant users/access. Tenant audit
and document navigation is labelled as tenant governance, not global platform
governance. GS1 requires both catalogue and inventory visibility. POS installer
handoff is shown only to POS-authorised tenants or the platform owner.

The policy covers the desktop/mobile sidebar, command search, dashboard
shortcuts, notification destinations, account menu, legacy admin-shell links,
and hash route mounting. Forbidden bookmarked or manually typed routes return
to Overview before a protected component mounts or fetches. Missing access
metadata fails closed to Overview during rolling upgrades. Owners retain their
global tools while operating within a selected tenant.

Menu filtering is presentation, not API authority. Existing explicit-owner
guards for national provider/activation/evidence/report APIs and pharmacy
registration remain enforced and are exercised with wildcard tenant roles.
Existing tenant/capability guards are not weakened. Grants are recalculated on
overview refresh; the route guard also handles removal of current grants.

No model migration or native POS source change is included. Signed managed
Windows POS remains 1.0.5; Android release signing and Manager stock/hardware
acceptance remain pending. Untracked Stage 2D.2 prototypes and user documents
are preserved and excluded. The live rollback target is rc44.

Local validation passed: 95 migrated SQLite tests across navigation, session,
HQ contracts, identity management, pharmacy lifecycle and release-security
boundaries; 437 shared/HQ/Windows/Android unit tests; all application TypeScript
and production bundle builds; changed-backend Ruff checks and diff whitespace
checks. The 10 new HQ DOM regressions include sidebar/mobile/search/account
filtering, forbidden initial/typed hashes, fail-closed old metadata, owner tools
inside a selected tenant and immediate revoked-route unmounting.

Final-source PostgreSQL 16, full SQLite, clean-checkout Node gates, dependency
audits, runtime image scans and immutable image evidence remain required in the
Production Images workflow. No check is skipped to speed deployment.
