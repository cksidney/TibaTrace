# TibaTrace Production Deployment

This bundle deploys DawaTrace at `https://tibatrace.esenai.co.ke/`. It is not
compatible with the path-based `https://esenai.co.ke/TibaTrace` address; DNS and
TLS terminate at the dedicated subdomain instead.

## Prerequisites

1. Create a DNS `A` or `AAAA` record for `tibatrace.esenai.co.ke` pointing to
   the deployment host and allow inbound TCP ports 80 and 443.
2. Provision isolated, backed-up PostgreSQL and Redis services. PostgreSQL must
   require TLS; the database URL must not share a database, user, or Redis
   namespace with another application.
3. Build, scan, sign, and publish an immutable backend image. Do not use a
   mutable tag such as `latest`.
4. Create a host-encrypted backup policy for the `clinical-objects` volume.
   Production document uploads fail closed until a malware scanner returns a
   `CLEAN` result; configure that scanner before enabling document uploads.
5. Store the real `.env.production` in the host secret manager or deployment
   system. Never commit it.

## First Deployment

```bash
cd deploy/tibatrace
cp .env.production.example .env.production
# Replace every <...> value, then validate the composed configuration.
docker compose --env-file .env.production config --quiet

# Run migrations once, before starting application processes.
docker compose --env-file .env.production --profile maintenance run --rm migrate
docker compose --env-file .env.production up -d api worker beat edge
```

Confirm `https://tibatrace.esenai.co.ke/api/health/` returns HTTP 200, then
verify an authenticated request, a background task, and a database backup/restore
in the staging environment before accepting traffic.

## Existing Shared Caddy

When the server already has a Caddy instance bound to ports 80 and 443, do not
start the `edge` service. Use the shared-Caddy override instead; it publishes the
API only on loopback and reserves the default port `28110` for TibaTrace:

```bash
docker compose --env-file .env.production \
  -f docker-compose.yml \
  -f docker-compose.shared-caddy.yml \
  config --quiet
docker compose --env-file .env.production \
  -f docker-compose.yml \
  -f docker-compose.shared-caddy.yml \
  --profile maintenance run --rm migrate
docker compose --env-file .env.production \
  -f docker-compose.yml \
  -f docker-compose.shared-caddy.yml \
  up -d api worker beat
```

After the DNS record resolves to the host, append the contents of
`Caddyfile.shared-route` to the active shared Caddy configuration, validate it
inside the Caddy container, and reload it. Keep the API port bound to loopback;
it must never be opened directly to the internet. Test the health endpoint
through the public hostname after Caddy has obtained its certificate.

## Updates and Rollback

Deploy only a new immutable `DAWATRACE_IMAGE` after the release gates pass. Run
the migration command first, retain the previous image reference, and roll back
application containers only after confirming the migration is reversible. Restore
from the managed database and clinical-object backup when a data rollback is
required; do not rely on Docker volumes as the sole recovery mechanism.
