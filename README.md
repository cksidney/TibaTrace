# DawaTrace

DawaTrace is Esenai Group Ltd's standalone pharmacy and healthcare platform.
Phase 2 extracts the tenant-safe clinical, prescription, CDS, terminology and
HL7 FHIR R4 foundations from Mercato-OS into an independently runnable modular
monolith.

## Current Scope

Included:

- independent tenancy, identity, organizations and healthcare RBAC
- canonical patients, practitioners, prescriptions and clinical resources
- clinical-domain invariant enforcement
- provider-based CDS and drug-interaction infrastructure
- HL7 FHIR R4 4.0.1 gateway and terminology operations
- audit, workflow, notification, crosswalk and document-security foundations
- minimal server-rendered administrative shell

Not included in Phase 2:

- complete medicine inventory, procurement, finance or payment gateways
- controlled-drug operations
- Windows or Android POS implementation
- production clinical knowledge content
- production data migration or deployment

## Runtime Locks

- Python 3.11
- Django 5.1.15
- `fhir.resources==6.5.0`
- `pydantic==1.10.26`
- PostgreSQL 18
- Redis 7

DawaTrace is currently measured against HAPI R4 evidence inherited as source
provenance. It is not declared `FHIR_PORTABLE`, Firely-compatible, or production
ready by this phase.

## Local Development

```bash
cp .env.example .env
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock -r backend/requirements-dev.lock
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py createsuperuser
.venv/bin/python backend/manage.py runserver
```

Open `http://127.0.0.1:8000/admin-shell/` for the verification shell and
`http://127.0.0.1:8000/api/health/` for health metadata.

## Docker

```bash
docker compose up --build
```

The Compose stack owns its PostgreSQL database, Redis namespace and object-store
volume. It does not connect to a Mercato database.

## TibaTrace Deployment Target

The intended public address is `https://tibatrace.esenai.co.ke/`, not the
path-based `https://esenai.co.ke/TibaTrace` form. A production Compose bundle,
TLS reverse-proxy configuration, environment template, and runbook are in
[`deploy/tibatrace/`](deploy/tibatrace/). The bundle uses separately managed
PostgreSQL and Redis services and remains subject to the release gates below.

## Test and System Validation

```bash
# Fast local validation
./scripts/validate_repository.sh --fast

# Full enterprise validation (CI / Release)
./scripts/validate_repository.sh --full
```

Validation artifacts are output to `artifacts/generated/validation/repository-validation-manifest.json`. For detailed documentation, see [`docs/validation/VALIDATION_GUIDE.md`](file:///Users/sidneykibet/DawaTrace/docs/validation/VALIDATION_GUIDE.md).
