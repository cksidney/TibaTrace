# rc39 candidate — maintenance-admin workflow boundary

Includes the rc38 commercial-pricing/report scope. rc38 was not activated.
rc39 was held before activation when desktop/mobile visual review identified
overflow in the new commercial price table. rc40 includes the same business and
maintenance controls plus that scoped responsive correction.

The default Django maintenance site is now an inspection-only site for active
privileged staff. Every registered ModelAdmin is wrapped to deny add/change/delete
and bulk actions, including registrations through decorators and built-in auth
models. All non-read maintenance routes are refused except login and authenticated
logout. Custom views and credential-change shortcuts cannot bypass the gate.
Business, identity and credential changes must use governed HQ/API workflows.

Tenant-owned inspection querysets require an explicit current tenant scope. An
absent scope returns no tenant records; ordinary tenant staff cannot enter the
maintenance inspector. This does not claim that privileged infrastructure/root
access is an application workflow or that all source reads are certified.

No additional database migration beyond sales 0005 is introduced. Before actual
activation, full clean-checkout business/workspace/PostgreSQL, immutable image,
provenance, database-backup and live health checks must pass. Existing signed
Windows 1.0.5 remains unchanged; Android signing, Managers' real stock/hardware
acceptance, provider onboarding and unavailable report prerequisites remain open.
