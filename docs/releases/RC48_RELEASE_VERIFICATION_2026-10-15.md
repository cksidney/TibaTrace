# rc48 deployment verification — 15 October 2026

Status: deployed; server activation, live access checks, public asset integrity,
and authenticated Windows installer download passed.

Runtime source: `7932d2ff90aa5f9169d459dec381fd2c2ac7b3f2`.
Immutable tags: `tibatrace-v1.0.0-rc48` and `pos-windows-v1.0.7`.
Prior live and retained rollback source: rc46,
`cfee05110cb0e289f751f7a79ac2e9fc451129e5`.

## Reviewed scope

HQ groups the existing permission-filtered navigation, compacts the header, and
makes executive cards responsive and keyboard accessible. Static executive
figures are explicitly labelled as examples; two card destinations were
corrected. The nonfunctional field-search placeholder was removed.

Windows POS 1.0.7 adds guided prescription, payment, handover and history views,
return-to-queue navigation, compact status and implemented shortcut help. Review
fixed F10 navigation, shortcuts behind the workstation lock or outside the
clinical workspace, stale episode context, duplicate payment and in-flight
selection, payment wording, and narrow-screen root grid overflow.

Backend application source and model migrations do not differ from rc46. The
unfinished Stage 2D.2 validator and untracked prototypes were excluded; the
validator's unconditional success output was not accepted as release evidence.
The original working checkout and its drafts were preserved.

The rc47 candidate was superseded before activation after full-console browser
review found narrow-screen overflow. Its server run was cancelled. Windows
1.0.6 passed its build but was never published to the tenant installer catalogue;
its GitHub release is marked as superseded. Neither is the active release.

## Final-source gates

[Production Images run 38753509829](https://github.com/cksidney/TibaTrace/actions/runs/38753509829)
passed all quality, PostgreSQL and image jobs on the exact runtime source:

- Full migrated SQLite: **2,172 tests**, zero failures/errors/skips.
- Full PostgreSQL: **2,172 tests**, zero failures/errors/skips. Source-linked
  database evidence confirms PostgreSQL **16.15** and the exact revision.
- Application tests: **447** across HQ (83), Windows (111), Android (41) and
  shared code (212), plus workspace typechecks and production builds.
- Online Python dependency audit: 58 dependencies, no vulnerabilities. The npm
  gate passed with only the repository's existing Android build-tool exceptions.
- Both complete runtime image scans passed without HIGH/CRITICAL findings.
  Release checksums, source labels, Linux amd64 architecture, SBOMs, empty
  migration inventory and GitHub build provenance were verified.

Local browser review passed **204 component layout checks** at 1280, 1024 and
390px. Full-console synthetic fixtures at 1280 and 390px checked HQ navigation,
POS handover/F10/help/lock behavior and root overflow without privileged
mutations. Screenshots were visually reviewed. These fixtures are separate from
the actual production identities checked below.

## Activation and live acceptance

Verified immutable images:

```
ghcr.io/cksidney/tibatrace-backend@sha256:3d751fbbffa537d4cb85868650bc6be9976b86164df8d6bb0dd84559a2f9b6f4
ghcr.io/cksidney/tibatrace-hq-web@sha256:3ea9d6202d1be805c1427a5723fce36b169a8969649502a9e7b6ea1ca2dfb727
```

Deployment archive SHA-256:
`19d46739bcd7e6b588d22bd6c53ef8ea304c16fc0e129b6271b9a9924ed84587`.
The archive carries deployment configuration and release notes; production
application code comes from the verified CI images.

Fresh root-only PostgreSQL custom dump, restore inventory, configuration backup
and checked dump checksum:
`/opt/tibatrace/backups/tibatrace-rc48-predeploy-20261015T153230Z`.
Backup and prior rc46 source/images remain retained. No rollback or database
restore was required. The bounded migration command had no migrations to apply.

API and HQ are healthy; worker and beat are running. All four carry the exact
source above. Existing healthy Redis was preserved. Django checks,
PostgreSQL/version verification, migration check, worker ping and public HTTPS
health passed. The active release pointer is:
`/opt/tibatrace/releases/tibatrace-1.0.0-rc48-7932d2ff-20261015`.
The deployment baseline was updated to the exact active source after acceptance.

Read-only policy checks covered **21 active tenant identities** and **two owner
identities**, without changing grants. An existing tenant passed authenticated
HTTPS overview/session checks; owner-only endpoints and a different tenant
header returned 403. An existing owner retained global and selected-tenant
navigation. This is not a claim that all tenant accounts completed interactive
login acceptance.

Public HQ HTML has no-store caching. Its served assets match the running image:

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `/assets/index-BYJZeMWW.js` | 823,015 | `00b4e6a779d2a6790631795c7aca78459eeba66c8be98fce9f0496c856225305` |
| `/assets/index-bYX1MrI9.css` | 147,307 | `3c18dd271ecc1b9800d1304363efdb88f02f4801c7e8eb933e7e3ca553af8727` |

## Signed Windows publication

[Windows run 38753508806](https://github.com/cksidney/TibaTrace/actions/runs/38753508806)
passed signing, timestamp, managed certificate enrollment and installed-app
verification for the same source. The managed certificate matches the prior
release. Its existing enrollment requirement remains in effect.

Published catalogue release: **1.0.7**, build **7**,
ID `a6e5dc12-0298-4018-ad6c-9cc4917cd944`.

- ZIP: `TibaTrace-POS-Managed-Install-1.0.7.zip`, **107,957,475 bytes**.
- ZIP SHA-256:
  `76332f79c823514ba99ef56cbadf4b3942fefdc5cc06d48281af6bdaaab4cd15`.
- Embedded installer SHA-256:
  `14ee7b4e90846810ed2fa7d2257746a1d0e9d1becb496cda9328663b207058c2`.
- Certificate SHA-256:
  `4c60fdc90f8bf35c2fd698ae0962adbbc015659a7cb294595195faa992affe02`.

An existing eligible tenant passed the authenticated HTTPS catalogue, download
issuance and complete streamed download with matching bytes/hash. Anonymous
download was refused. Prior 1.0.5 publication metadata remains unchanged and
`minimum_supported_build` remains **0**. Publication and verification produced
the expected release/download audit entries; no credentials, access grants or
clinical transactions were changed. Short-lived verification bearers stayed in
memory and were not logged.

Refresh already-open HQ tabs to load the new bundle. Each Windows till needs
installation of 1.0.7 to receive the native interface changes. No physical till,
printer or stock acceptance is claimed; Android signing remains separate.

## Retained evidence

The release directory's `evidence/` contains the CI release manifest/checksums,
database reports, security reports, verified image attestations, activation log,
live public checks, installer facts and publication/download log. The local
review directory is `/private/tmp/tibatrace-20261015-review`.
Production activation log: `/opt/tibatrace/releases/rc48-activation.log`.
The root-only backup also retains live permission output and the migration plan.
