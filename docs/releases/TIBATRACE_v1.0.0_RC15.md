# TibaTrace v1.0.0-rc15

Release candidate `1.0.0-rc15` promotes the reviewed changes made after RC14.
It includes the demo-scenario engine through dispensing-readiness, stock
mobility and reservation controls, strengthened tenant scoping, and the
existing HQ and POS contract baseline.

## Release scope

- Deterministic demo-scenario planning, master-data generation, procurement,
  quality, inventory ownership, stock transfers, FEFO reservations and
  dispensing-readiness evidence.
- Security fixes that scope Stage 2C branch and location lookups, and
  dispensing-event replay, to the active tenant.
- Procurement quality-release support and an additive procurement migration.
- HQ Reports dark-theme contrast correction, with the Windows and Android POS
  clients retained on their already-versioned, shared-contract releases.
- Regulatory and national-integration foundations introduced in RC12 remain in
  scope and are unchanged by this candidate.

## Explicit exclusion

The uncommitted Stage 2D.2 "dispensing hardening" prototype is not part of
this release. Its proposed lifecycle persistence, price-lock and certification
checks do not yet have corresponding database fields and authoritative domain
services. It must be completed and independently reviewed before a later
release candidate.

## Database changes

This candidate includes the additive procurement migration registered by the
release pipeline. The pipeline must produce the migration inventory and the
deployment must take a checksum-verified database backup before migrations.

## Deployment and rollback

Deploy only the immutable backend and HQ image digests published for
`tibatrace-v1.0.0-rc15`. Retain the current production release as the single
rollback generation until migrations, health checks and authenticated HQ/POS
acceptance checks pass. Existing signed POS installers are not replaced under
an existing version.
