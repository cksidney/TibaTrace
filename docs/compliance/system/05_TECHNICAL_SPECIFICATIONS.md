<!-- TIBATRACE DOCUMENT BRANDING START -->
<p><img src="../brand/tibatrace-logo.jpeg" alt="TibaTrace logo" width="150"> &nbsp; <img src="../brand/esenai-group-logo.png" alt="Esenai Group logo" width="200"></p>

**TibaTrace · Esenai Group Ltd**<br>
Branding edition: 26 October 2026. Assessment dates, evidence scope and approval decisions below remain controlling.
<!-- TIBATRACE DOCUMENT BRANDING END -->

# TibaTrace Technical Specifications

**Specification basis:** reviewed repository source, 26 October 2026<br>
**Production server baseline:** `1.0.0-rc71`, commit `2965194a29311314e8a5772adfeee5af8c14a8f2`<br>
**Status:** Production-specific claims are bounded by the rc71 review. Local source commit `f8ea5cd` is unshipped; native-client versions and tenant configurations require separate confirmation.

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

The audited production deployment uses API, worker, beat and HQ containers, PostgreSQL, Redis, a clinical-object volume and shared Caddy on a Hetzner Nuremberg, Germany VPS. rc71 release evidence covers the deployed server artifacts and verification; it does not establish a contractual availability percentage, approved RTO/RPO, physical client versions, host/database at-rest encryption, or a Kenya serving copy. DHA/RX/checkout exchange remains disabled. Source commit `f8ea5cd` is not included in production.

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
