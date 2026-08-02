# TibaTrace — End-to-End Guide

**Applies to:** v1.0.0-rc13 · **Production:** `https://tibatrace.esenai.co.ke`

This is the authoritative guide to TibaTrace. It runs the full length of the
system: install it, configure it, use it at a pharmacy counter, report on it,
and keep it running.

Read the part that matches your role.

| Part | For | Covers |
|---|---|---|
| [1. The system](#1-the-system) | everyone | What the pieces are and how they fit |
| [2. Install and deploy](#2-install-and-deploy) | operations | First deployment, releases, rollback |
| [3. Configure](#3-configure) | HQ administrators | Tenants, branches, users, catalogue, pricing |
| [4. The dispensing counter](#4-the-dispensing-counter) | pharmacy staff | The POS journey, start to finish |
| [5. HQ workspaces](#5-hq-workspaces) | HQ operators | All twenty workspaces |
| [6. Reporting](#6-reporting) | everyone | The catalogue, exports, validation receipts |
| [7. Keeping it running](#7-keeping-it-running) | operations | Health, backups, secrets, upgrades |
| [8. Reference](#8-reference) | everyone | Capabilities, statuses, troubleshooting |

---

## 1. The system

TibaTrace is a multi-tenant pharmacy and healthcare operations platform. One
deployment serves many pharmacy organisations ("tenants"), each with its own
branches, staff, stock and patients, isolated from one another.

Five components:

| Component | What it is | Where it runs |
|---|---|---|
| **Backend API** | Django. The authority for every record and rule | Container on the server |
| **HQ web** | The browser workspace for operators and administrators | Container serving static assets |
| **POS Windows** | The dispensing terminal for a pharmacy counter | Windows PC at the branch |
| **POS Android** | The mobile dispensing client | Android device |
| **Worker + scheduler** | Background jobs and scheduled work (Celery) | Containers on the server |

Backed by PostgreSQL (records), Redis (queues and cache), and an object store
for uploaded documents and POS installers.

**One rule underpins everything: a tenant never sees another tenant's data.**
It is enforced in the data layer, not in the interface, and there is an
automated audit that fails the build if a query is written that could cross the
boundary. Where a genuine exception exists — password recovery has to find a
user before any tenant is known — it is declared explicitly in
`backend/apps/prescription/management/lookup_safety.py` and confined to the one
module that needs it.

---

## 2. Install and deploy

### 2.1 What you need

- A Linux host with Docker and Docker Compose
- PostgreSQL 16 with TLS, on its own database and user
- Redis, password-protected, on its own namespace
- A DNS record for your domain, with ports 80 and 443 reachable
- Object storage for POS installers and clinical documents

### 2.2 Where things live

```
/opt/tibatrace/
├── current -> releases/<release>/   # symlink to the live release
├── releases/                        # immutable release directories
├── secrets/.env.production          # the only configuration file (mode 600)
├── backups/                         # database dumps, one directory per release
└── incoming/                        # transfer staging
```

The environment file lives **outside** the release directories and survives
every deployment. It is never committed and never overwritten by a release.

### 2.3 Images come from CI, never from a laptop

Release images are built only by GitHub Actions and published to GHCR:

- `ghcr.io/cksidney/tibatrace-backend`
- `ghcr.io/cksidney/tibatrace-hq-web`

Production pulls **by digest**, never by tag. No `latest` tag is published, so
no reference can drift. A mutable tag cannot tell you what is running six weeks
from now; a digest can.

This is not a preference. A release once passed every local check and could not
be built at all, because a developer's machine had stale build artefacts that
hid a broken Dockerfile. CI has no such state.

### 2.4 Deploying a release

```bash
# 1. Pull the exact images by digest
docker pull ghcr.io/cksidney/tibatrace-backend@sha256:<backend-digest>
docker pull ghcr.io/cksidney/tibatrace-hq-web@sha256:<hq-digest>

# 2. Confirm they are what you think they are
docker image inspect ghcr.io/cksidney/tibatrace-backend@sha256:<backend-digest> \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

That revision must equal the release commit. If it prints `unknown`, stop — the
image was not built by the release pipeline.

```bash
# 3. Back up the database before anything changes
pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner --no-privileges \
  --file=/opt/tibatrace/backups/<release>/db.dump

# 4. Review what the migrations will do, without applying them
docker run --rm --network host --env-file /opt/tibatrace/secrets/.env.production \
  ghcr.io/cksidney/tibatrace-backend@sha256:<backend-digest> \
  sh -c 'python manage.py check && python manage.py migrate --plan'

# 5. Apply them
cd /opt/tibatrace/current/deploy/tibatrace
docker compose --env-file /opt/tibatrace/secrets/.env.production \
  -f docker-compose.yml -f docker-compose.server.yml \
  --profile maintenance run --rm migrate

# 6. Point current at the new release, atomically
ln -sfn /opt/tibatrace/releases/<release> /opt/tibatrace/current.new
mv -Tf /opt/tibatrace/current.new /opt/tibatrace/current

# 7. Recreate only TibaTrace services
docker compose --env-file /opt/tibatrace/secrets/.env.production \
  -f docker-compose.yml -f docker-compose.server.yml \
  up -d --remove-orphans redis api worker beat hq
```

**Never** run `docker compose down -v` — it destroys the volumes holding your
database, uploads and installers. **Never** run `git clean -fdx` in a release
directory.

### 2.5 The check that decides whether a deployment worked

After activation, every component must report the same revision:

```bash
for c in tibatrace-api-1 tibatrace-worker-1 tibatrace-beat-1 tibatrace-hq-1; do
  docker inspect "$c" --format \
    '{{.Name}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
done
```

All four must print the release commit. If they disagree, the deployment is
**failed, not partial** — treat it that way. A deployment once left the web tier
on one commit and the API on another for three days, and nothing reported a
problem.

### 2.6 Rolling back

Every release backs up the environment file before changing it.

```bash
cp -a /opt/tibatrace/secrets/.env.production.pre-<release>-<timestamp> \
      /opt/tibatrace/secrets/.env.production
ln -sfn /opt/tibatrace/releases/<previous> /opt/tibatrace/current.new
mv -Tf /opt/tibatrace/current.new /opt/tibatrace/current
# then re-run step 7 above
```

Migrations are **not** reversed automatically. Check the release's
`MIGRATIONS.json` first: if every migration is `"destructive": false`, the older
image runs safely against the newer schema and you need do nothing. Otherwise
restore from the dump taken in step 3.

Keep at least one previous release directory and its images.

---

## 3. Configure

Order matters. Each step depends on the one before it.

### 3.1 Tenants and branches

**Pharmacy network** creates the organisations and their locations. A tenant is
a pharmacy business; a branch is a physical site with its own stock, tills and
staff. Everything else attaches to one or the other.

### 3.2 Users and roles

**Administration & Users** creates accounts and grants capabilities.

TibaTrace does not have a small fixed set of roles. It has **29 named
capabilities** that you compose into roles suited to the branch. A capability is
a specific permission — `pos.payment.collect`, `prescriptions.pharmacist_verify`,
`pricing.price_book.publish` — and a role is a bundle of them.

This matters at the counter. The person who *requests* a price override cannot
be the person who *approves* it, because those are two capabilities
(`pricing.manual_override.request` and `.approve`), and approving below the
floor price is a third (`.approve_below_floor`). Separation of duty is enforced
by the permission model, not by policy documents.

The full list is in [§8.1](#81-capabilities).

**A user with no workspace assignment cannot sign in.** If someone reports
"account is not assigned to a workspace", they need a tenant assigned in
Administration & Users.

### 3.3 Medicine catalogue

**Medicine catalogue** governs what may be dispensed. The model deliberately
separates three concerns that many systems merge:

- **Clinical product** — the medicine as a clinician thinks of it (substance, strength, form)
- **Manufactured product** — a specific manufacturer's version of it
- **Commercial SKU** — the sellable, stockable, priceable unit

A SKU cannot exist without a manufactured product and a package definition. This
is enforced by non-nullable foreign keys, and it is why **you cannot price an
item before its catalogue governance is complete**. If pricing rejects a code
with "select an existing tenant commercial SKU", the answer is to finish the
catalogue entry, not to work around it.

### 3.4 Pricing

**Pricing** manages branch price books. Prices resolve in strict order:

1. Customer price agreement (a bilateral agreement with one customer)
2. Branch price list entry
3. Tenant price list entry
4. SKU base price

Price books move through **draft → approved → published** as separate,
separately-permissioned steps. Manual overrides are requested and approved by
different people, and going below the floor price needs a third capability
again.

### 3.5 Suppliers and procurement

**Procurement & Supply** holds suppliers, purchase orders and goods received
notes. Receiving is scan-driven: scan the delivery against the order, record
batch and expiry, and stock enters quality-held state until released by someone
with `quality.release`.

### 3.6 Insurance

**Insurance & Claims** configures insurers and schemes, including SHA, and
handles adjudication.

---

## 4. The dispensing counter

This is the part pharmacy staff use every day. The Windows and Android
terminals follow the same journey.

### 4.1 Starting a shift

1. **Sign in** with your own account. Never share a login — every clinical and
   cash action is attributed to the person who performed it.
2. **Open your register** in Register Centre. Count the float and record it.
   The expected drawer starts from this number, so a wrong float becomes a
   variance you will have to explain at close.
3. Check the **status bar**. It shows whether the terminal is online, whether
   clinical decision support is reachable, and whether anything is queued.

### 4.2 Dispensing a prescription

An episode moves through these states, and the workflow ribbon shows where you
are:

```
DRAFT → PREPARING → CHECKING → READY_FOR_PAYMENT → PAID
      → READY_FOR_COLLECTION → SUPPLIED → CLOSED
```

with `ON_HOLD`, `PARTIALLY_SUPPLIED`, `CANCELLED`, `REJECTED`, `REVERSED` and
`RETURNED` available where the situation calls for them.

**Prepare.** Open the prescription. Confirm the patient, then pick each item.
Scan the batch — this records exactly which batch went to which patient, which
is what makes a recall actionable later.

**Clinical screening.** Decision support runs automatically: interactions,
allergies, duplicate therapy, dose sanity. Findings appear on the patient safety
banner.

> A blocking finding stops the episode. It is not a warning you can click past.
> A pharmacist with `prescriptions.clinical_review` must review it and either
> resolve it or record an explicit override with a reason. The override is
> stored against the episode and appears in clinical reports. This is the point
> of the system — do not treat it as an obstacle.

**Pharmacist verification.** Someone with `prescriptions.pharmacist_verify`
performs the final check. On a controlled drug this is a legal act, and the
system records who did it.

**Payment.** Take payment in Payment Panel — cash, card, mobile money, insurance
or a split across several. Payment is idempotent: if the connection drops
mid-transaction, retrying will **not** charge twice. The episode carries one
authoritative payment state, so what you see is what settled.

**Counselling and collection.** Counsel the patient, record that you did, and
release the medicine. The episode reaches `SUPPLIED`.

**Print.** Labels, receipts and the dispensing record print from Print Centre,
and can be reprinted — reprints are logged.

### 4.3 Retail sales

Retail Workspace handles over-the-counter sales that are not against a
prescription. Same payment and till handling; no clinical gate.

### 4.4 Working offline

The terminal keeps working when the network drops. Work is queued locally and
syncs when the connection returns; Sync Centre shows what is pending.

Two limits worth knowing:

- **Clinical decision support needs the server.** Offline, screening cannot run.
  The terminal will tell you so rather than pretend the check passed.
- **Do not close a shift with unsynced work.** Reconcile first, or the cash
  position will not match.

### 4.5 Closing a shift

Count the drawer, enter the actual figure, and close. Any difference between
expected and counted is recorded as a variance with your name on it. Variances
are not hidden or netted off — they surface in Finance & Cash Control and in the
cash reports.

---

## 5. HQ workspaces

Twenty workspaces, grouped by what you are trying to do.

**Daily oversight**

| Workspace | Use it for |
|---|---|
| Overview | The command centre. Start here |
| Executive Dashboard | 18 leadership widgets across the workspace |

**Operations**

| Workspace | Use it for |
|---|---|
| Pharmacy network | Tenants and locations |
| Patients & People | Care records and commercial customers |
| Medicine catalogue | SKUs and product governance |
| Inventory Control | Balances, ledger and FEFO |
| Procurement & Supply | Purchase orders and goods received |
| Sales & fulfilment | Orders through to delivery |
| Point of sale | Live dispensing operations |

**Money**

| Workspace | Use it for |
|---|---|
| Pricing | Branch price books |
| Finance & Cash Control | Shifts, tills and variances |
| Insurance & Claims | Adjudication and SHA |

**Assurance**

| Workspace | Use it for |
|---|---|
| Clinical governance | Safety and standards |
| Regulatory Workspace | PPB and DHA compliance |
| National Integrations | DHA and PPB command centre |
| Reports | Enterprise and security packs |
| System governance | Audit, events and documents |

**Administration**

| Workspace | Use it for |
|---|---|
| Administration & Users | Roles and security |
| System controls | Identity, security and governance |
| API documentation | Integration contracts |

### 5.1 Inventory: FEFO

Stock is consumed **first-expired-first-out**, not first-in-first-out. The
terminal picks the batch nearest expiry that satisfies the line. You can
override this, and the override is recorded.

Every movement writes a ledger entry. On-hand, reserved and available are
derived from the ledger, never edited directly, and database constraints
prevent any of them going negative.

### 5.2 Regulatory and national integrations

The Regulatory Workspace and National Integrations cover PPB and DHA
compliance: premises verification, health worker registry lookups, and
regulatory recalls matched against the batches you actually dispensed. That
matching is why batch scanning at the counter matters.

### 5.3 Theme

The sun/moon control in the header switches light and dark. Your choice is
remembered on that device and applies from the moment the page loads.

---

## 6. Reporting

**Reports** holds the enterprise catalogue — 99 packs across 14 categories:

Executive · Sales & Dispensing · Procurement · Inventory · Finance · Quality ·
Clinical · Controlled Drug · Regulatory · Logistics · CRM · HR & Operations ·
Audit · Analytics & Forecasting · Security

### 6.1 Running one

1. Open **Reports** and pick a pack from the catalogue.
2. Set the **reporting window** — quick presets (Today, This Week, This Month,
   Last Month, This Year) or a custom range. The selected preset is highlighted.
3. Scope it to branch or warehouse if you only want part of the network.
4. Export as **PDF, CSV, JSON or XLSX**.

### 6.2 Validation receipts

Every download embeds a unique validation QR recording who downloaded it, when,
the tenant scope, the terminal identity, and an integrity code.

This is what makes an exported PDF defensible. A report handed to a regulator
can be checked against the system that produced it, and a document that has been
altered will not validate. Every download is also written to the audit trail.

### 6.3 What you will and will not see

Reports are **tenant-scoped without exception**. You see your workspace and
nothing else. Access is capability-gated, so two people running the same report
may legitimately get different results — that is the isolation working.

---

## 7. Keeping it running

### 7.1 Health

```bash
curl -fsS https://tibatrace.esenai.co.ke/api/health/
```

Expect `{"status": "ok", ...}`. Then confirm no container is restarting:

```bash
docker ps --filter 'name=tibatrace' --format 'table {{.Names}}\t{{.Status}}'
```

`api`, `hq` and `redis` carry health checks and should read `(healthy)`.
`worker` and `beat` do not — check them directly:

```bash
docker exec tibatrace-worker-1 celery -A dawatrace inspect ping
```

### 7.2 Backups

Take a database dump before every release, and keep them:

```bash
pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner --no-privileges \
  --file=/opt/tibatrace/backups/<label>/db.dump
```

A dump that was never restored is a hope, not a backup. Practise the restore.

Also back up, separately and encrypted: `/opt/tibatrace/secrets/.env.production`,
and the volumes holding uploaded documents and POS installers.

### 7.3 Secrets

All configuration lives in `/opt/tibatrace/secrets/.env.production`, mode `600`,
owned by root. It is never committed, never printed, and never copied into a
release directory.

To rotate a secret: back up the file first, change every field that carries the
value (a Redis password appears in **four** — `TIBATRACE_REDIS_PASSWORD` and
three connection URLs), write the file atomically, then recreate the services
that read it. `docker restart` is not enough — environment is fixed at container
creation, so the container must be **recreated**.

Afterwards, prove the old credential no longer works. Rotation you have not
tested is rotation you have not done.

### 7.4 Disk

The application competes for disk with everything else on the host. Before a
release, check headroom:

```bash
df -h /
docker system df
```

Release directories and superseded POS installers are the usual growth. Keep the
running release plus one previous, and one installer per platform. **Never**
prune images belonging to other applications on a shared host.

### 7.5 POS client releases

POS installers are published through the release catalogue and downloaded from
HQ by an authenticated operator. The Android APK is signed with the production
keystore; the Windows installer is signed with Esenai's own certificate.

> **The Windows certificate is self-signed.** It gives you integrity and
> authenticity on a managed device where the certificate has been enrolled —
> which the managed-install package does for you. It will **not** clear
> SmartScreen on a machine that has never seen it. That is a distribution
> decision, not a signing failure, and the release manifest records the two
> separately as `cryptographically_signed` and `publicly_trusted`.

---

## 8. Reference

### 8.1 Capabilities

| Area | Capabilities |
|---|---|
| Prescriptions | `prescriptions.read` · `.write` · `.intake` · `.review` · `.clinical_review` · `.legal_validate` · `.pharmacist_verify` |
| Dispensing | `dispensing.read` |
| Clinical support | `cds.read` |
| POS | `pos.payment.collect` · `pos.shift.manage` |
| Inventory | `inventory.read` · `.manage` · `quality.release` |
| Procurement | `procurement.read` · `.write` · `.approve` |
| Pricing | `pricing.read` · `.manage` · `price_book.manage` · `.approve` · `.publish` · `manual_override.request` · `.approve` · `.approve_below_floor` |
| Insurance | `insurance.read` · `.manage` |
| Patients | `patients.identity.manage` |
| Identity | `identity.manage` |

Grant the narrowest set that lets someone do their job. The separations above —
request versus approve, approve versus approve-below-floor — exist to be used.

### 8.2 Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Account is not assigned to a workspace" | No tenant on the user | Assign one in Administration & Users |
| "Select an existing tenant commercial SKU" | Pricing an item whose catalogue entry is incomplete | Finish the SKU: manufactured product and package definition |
| Clinical screening unavailable at the counter | Terminal is offline | Screening needs the server. Do not dispense past a blocking finding |
| Report download returns 503 | Release storage not configured | Check `TIBATRACE_RELEASE_BACKEND` and that the artefact exists |
| Installer download fails | Artefact missing from storage | Confirm the object exists at the configured backend |
| Components report different revisions | Partial deployment | Failed deployment. Re-run activation for all services |
| Image label reads `unknown` | Image not built by the release pipeline | Do not deploy it. Rebuild through CI |
| Windows installer warns on launch | Self-signed certificate not enrolled | Install via the managed-install package, which enrols it |
| Cash variance at close | Float wrong at open, or unsynced work | Reconcile Sync Centre before closing |

### 8.3 Deeper reading

| Topic | Document |
|---|---|
| Release packaging | `docs/deployment/TIBATRACE_RELEASE_PACKAGING_WORKFLOW.md` |
| Medicine domain model | `docs/domain/MEDICINE_CATALOGUE_DOMAIN_MODEL.md` |
| Product/SKU/batch separation | `docs/domain/MEDICINE_PRODUCT_SKU_BATCH_SEPARATION.md` |
| Pricing model | `docs/domain/COMMERCIAL_PRICING_MODEL.md` |
| Procurement lifecycle | `docs/domain/PROCUREMENT_LIFECYCLE.md` |
| FHIR conformance | `docs/fhir/FHIR_CONFORMANCE.md` |
| Kenya data protection | `docs/fhir/KENYA_DATA_PROTECTION_ACT_2019.md` |
| Reports catalogue | `docs/architecture/TIBATRACE_REPORTS_CATALOGUE.md` |
| System architecture | `docs/architecture/TIBATRACE_TECHNICAL_SYSTEM_DOCUMENTATION.md` |
| Release notes | `docs/releases/` |

---

*Corrections belong in this file. If you find something here that does not match
the system, the guide is wrong until proven otherwise — fix it.*
