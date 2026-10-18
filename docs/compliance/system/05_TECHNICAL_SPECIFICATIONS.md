# TibaTrace Technical Specifications

**Specification basis:** source snapshot `45bf133`, 17 October 2026  
**Latest documented production release:** `tibatrace-v1.0.0-rc52`, source `e9cac5d`  
**Status:** As-built repository reference; production values must be confirmed against the active release and deployment environment.

## Product surfaces

| Component | Specification |
|---|---|
| Backend API | Python 3.11 application; Django 5.2.18; Django REST Framework 3.18.3; SimpleJWT 5.5.1; Gunicorn |
| Data store | PostgreSQL (production deployment record uses PostgreSQL 16; Compose development image/config can differ); Django migrations; shared schema with tenant-scoped rows |
| Cache and jobs | Redis 5.2.0 client; Celery 5.4.0 worker and beat; Redis-backed broker/cache/results |
| HQ web | React 19.2.8, TypeScript, Vite 8.1.5; session authentication and capability-gated workspaces |
| Windows POS | Electron 43.2.0, React 19; JWT/native device workflows; Windows DPAPI-protected credential material; signed managed package |
| Android POS | React Native 0.86.0, React 19; Android Keystore-backed token handling; release cleartext traffic disabled |
| Clinical exchange | FHIR R4 API and profile/conformance code; this does not establish a live external HIE connection |
| Document service | Tenant-keyed local clinical-object storage in documented Compose; content hash validation; signed short-lived download token; configured malware scanner required in production |
| Edge | Caddy reverse proxy with TLS at the documented hosted deployment; verify active configuration and certificate at runtime |
| Delivery | GitHub Actions, immutable GHCR image digests, release manifest/checksums and provenance evidence |

Versions above are from the current repository's pinned Python requirements and package manifests; native package versions actually installed on a till must be read from the signed installer catalogue.

## Backend domains

The Django modular monolith contains identity/tenancy, organizations, patients, practitioners, prescriptions/dispensing, clinical records, clinical decision support, medicines/catalogue, inventory, procurement, pricing, sales, POS shifts/transactions, insurance, terminology, FHIR, documents, audit, notifications, workflows, and reporting. The authoritative route map is in `backend/dawatrace/urls.py` and the relevant app URL files.

## Interfaces and protocols

- Browser HQ authentication: Django session cookie plus CSRF validation.
- Native POS/API authentication: Bearer JWT and device/session workflow.
- REST JSON APIs under `/api/`; FHIR R4 under `/api/fhir/r4/`; health endpoint `/api/health/`.
- Public service access is HTTPS through the configured reverse proxy. TLS to the database is required by the documented Esenai host setup.
- Asynchronous work is queued through Celery/Redis and must preserve explicit tenant scope.
- Idempotency, state transitions and domain service boundaries protect selected financial, clinical, and provider operations.

## Tenancy and security boundaries

The database uses shared-schema, row-level tenancy. Tenant context is established from authenticated identity and request context. Normal tenant users cannot select another tenant by header; platform-owner authority is explicit. Tenant managers and capability checks fail closed when context or permission is absent. Platform-owner functions are separate from tenant operations.

## Availability and release

The production deployment uses API, worker, beat and HQ containers, PostgreSQL, Redis, a clinical-object volume and shared Caddy. Deployment is a controlled release-directory switch using immutable images. The rc52 release record reports verified migrations, health, tenant/owner access tests and a pre-deployment database backup. It does not define a contractual availability percentage, RTO or RPO.

## External integrations

Provider templates are not an integration. DHA/HWR, PPB, SHA/insurer, M-PESA/Daraja, KRA eTIMS/VSCU, KHIS/SHIELD, and KNHTS must each have a supported endpoint/profile, credentials in the approved secret manager, data-sharing authority, sandbox/production evidence, and activation approval. The payment release record specifically says Daraja/eTIMS remain disabled until validated configuration and mappings exist.

## System-of-record conventions

- PostgreSQL holds authoritative business and clinical records.
- Redis is not the system of record.
- Clinical attachments reside in a separate volume and require their own backup/restore and at-rest protection evidence.
- Release artifacts and source revision are recorded by immutable image digests and release manifests.
- Test-only SQLite evidence must not be presented as production-database evidence.

## Source references

- `backend/requirements.lock`
- `apps/hq-web/package.json`, `apps/pos-windows/package.json`, `apps/pos-android/package.json`
- `deploy/tibatrace/docker-compose.yml`, `docker-compose.server.yml`
- `docs/architecture/TIBATRACE_TECHNICAL_SYSTEM_DOCUMENTATION.md`
- `docs/releases/RC52_RELEASE_VERIFICATION_2026-10-16.md`
- `docs/releases/TIBATRACE_v1.0.0_RC53.md`
