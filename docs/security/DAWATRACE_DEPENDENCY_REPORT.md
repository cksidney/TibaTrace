# DawaTrace Phase 2 Dependency Report

## Locked Runtime

DawaTrace pins 19 direct Python runtime requirements and 8 direct development
requirements. The clinical interoperability runtime is fixed to:

- Python 3.11
- Django 5.1.15
- `fhir.resources==6.5.0`
- `pydantic==1.10.26`

The shared TypeScript package pins TypeScript 5.7.3 and the root lockfile targets
Node 20. No package is resolved from a Mercato path or private Mercato registry.

## Integrity and Inventory

- A clean virtual environment installed both lock files successfully.
- `pip check` reported no broken requirements.
- `npm ci --ignore-scripts` completed from `package-lock.json`.
- Backend and shared-package builds passed.
- `installed-packages.json` records the resolved Python environment.
- `dawatrace-backend.cdx.json` is a reproducible CycloneDX source dependency SBOM.

## Vulnerability Advisory Status

The local online Python and npm advisory audits were not accepted as evidence.
The sandbox could not reach npm, and escalation for both ecosystems was rejected
because it would transmit private dependency inventory to an external service.
No workaround was used and no zero-vulnerability claim is made.

`pip-audit` and `npm audit --audit-level=high` are configured in CI for execution
in an approved environment. A passing trusted-environment result is mandatory
before release. See `artifacts/evidence/security/dependency-audit-status.json`.

## Container Dependency Boundary

The backend image uses a digest-pinned Python 3.11 slim Bookworm base. The runtime
stage receives only the locked runtime environment and backend source. A current
OS/package CVE scan is still required because the base digest being fixed does
not prove that it is vulnerability-free.
