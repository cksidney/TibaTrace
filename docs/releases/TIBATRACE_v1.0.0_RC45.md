# TibaTrace 1.0.0-rc45

Withdrawn before deployment; superseded by rc46. No production activation.

Targeted HQ tenant-navigation isolation; see
[scope and verification](RC45_TENANT_NAVIGATION_ISOLATION.md).

Tenant navigation uses current server-side capability grants. Executive,
pharmacy-network, national-integration and platform-owner controls remain
exclusive to explicit platform owners across navigation and hash routes.
Tenant user/access administration and other tenant workflows remain available
according to their existing grants. Owner API guards remain enforced.

No model migration, role mutation, business-data seeding or native installer
change. Retain rc44 application images, source and a fresh root-only database
backup for rollback. Candidate is not live until release gates and activation
verification have passed.
