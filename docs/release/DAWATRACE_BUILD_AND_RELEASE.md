# DawaTrace Build and Release

## Release State

Phase 2 produces an independently buildable clinical-core baseline at
`0.1.0-alpha.1`. It is not a production release. Production deployment, data
migration, licensed clinical content, and complete external FHIR certification
remain gated.

## Reproducible Local Validation

Use Python 3.11 and Node 20 from a clean checkout:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock -r backend/requirements-dev.lock
npm ci --ignore-scripts
./scripts/validate_phase_2.sh
```

The validation script uses an isolated SQLite database, locmem cache, eager
Celery execution, and test-only signing material. It must not be pointed at a
production database or Redis namespace.

## Container Build

```bash
docker build \
  --file docker/backend.Dockerfile \
  --build-arg DAWATRACE_VERSION="$(cat VERSION)" \
  --build-arg GIT_SHA="$(git rev-parse HEAD)" \
  --build-arg BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --tag "dawatrace/backend:$(cat VERSION)" \
  .
```

The image uses a digest-pinned Python 3.11 Bookworm base in both stages, installs
only `requirements.lock` in the runtime layer, runs as UID/GID 10001, exposes an
HTTP health check, and records product, version, revision, build time, and FHIR
4.0.1 labels.

## Local Compose

`docker compose up --build` starts independent PostgreSQL, Redis, API, worker,
beat, and clinical-object volumes. Values in Compose are development-only. Copy
`.env.example`, rotate all secrets, and use separately managed infrastructure for
any controlled environment.

## TibaTrace Production Target

The production address is `https://tibatrace.esenai.co.ke/`. Do not mount the
application beneath `https://esenai.co.ke/TibaTrace`: root-relative routes,
static assets, redirects, and FHIR canonical URLs are configured for the
dedicated subdomain.

The deployment bundle is in [`deploy/tibatrace/`](../../deploy/tibatrace/). It
starts the API, worker, beat, and optionally a dedicated Caddy TLS edge from an
immutable backend image; PostgreSQL and Redis remain separately managed services.
Servers with a shared Caddy must use `docker-compose.shared-caddy.yml` and the
provided Caddy route rather than starting a second edge on ports 80 and 443. Copy
`.env.production.example` to `.env.production` only in the deployment
environment, replace every placeholder using the secret manager, run migrations
once, and then start the application processes. Its runbook specifies the
required DNS, TLS, recovery, and verification steps.

## Release Gate

A release candidate requires all of the following:

1. Reviewed, committed source provenance and a matching extraction manifest.
2. Clean dependency install, `pip check`, lint, Django checks, migration drift,
   zero migration, rollback/reapply, and all focused tests.
3. Clean dependency, secret, static-code, tenant-manager, UUID-lookup, and image
   scans with reviewed exceptions.
4. PostgreSQL migration and concurrency validation, not SQLite evidence alone.
5. Protected HAPI R4 rerun and Firely certification if portability is claimed.
6. Licensed clinical knowledge, clinical governance, and regulatory approval.
7. Staged migration rehearsal, backup/restore test, rollback plan, and operator
   approval.
8. DNS and certificate issuance for `tibatrace.esenai.co.ke`, with the API port
   reachable only through the TLS edge.
9. A configured malware scanner before clinical document uploads are enabled;
   production uploads fail closed until it returns a `CLEAN` result.

Do not tag a release when the repository or evidence is dirty. Phase 2 creates no
production tag and performs no deployment.

## Evidence

Tracked evidence is retained under `artifacts/evidence/`. CI-generated evidence
is retained under `artifacts/generated/` as workflow artifacts. Container build
metadata belongs in `artifacts/evidence/build/docker-image.json`.
