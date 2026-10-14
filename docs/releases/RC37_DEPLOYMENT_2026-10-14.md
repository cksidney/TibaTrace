# rc37 / Windows 1.0.5 deployment record — 14 October 2026

API, HQ, worker and beat are live at https://tibatrace.esenai.co.ke on server
revision `093910f58b6e1916c3cc35851d41c2ee76551484` (`tibatrace-v1.0.0-rc37`).
Windows POS 1.0.5 uses revision `517183ff3025041dbf4d8d25eb36379d785fa29f`:
the subsequent difference is confined to the Windows sandboxed preload and
installed-launch verification. Backend, HQ and shared source match the server tag.

## Release evidence

- [Production Images 38472180188](https://github.com/cksidney/TibaTrace/actions/runs/38472180188):
  passed, 2,082 backend tests, zero failures/errors/skips; all application gates,
  architecture/labels, four-migration inventory, image smoke and provenance.
- [CI 38472222401](https://github.com/cksidney/TibaTrace/actions/runs/38472222401):
  passed, PostgreSQL-backed full validation and four-width visual checks. Backend
  evidence has 2,081 passes and one baseline-history test skipped by shallow
  checkout; the full-history production-image gate passed that test. Generic
  validation records deferred external checks; this is not regulatory certification.
- [Signed Windows 38494246148](https://github.com/cksidney/TibaTrace/actions/runs/38494246148):
  passed signing/timestamp, certificate enrolment, clean installation and launch
  of the installed application with version/build/login/API/printing bridge.
  Local final Windows typecheck/build and 106 tests passed. Managed certificate
  is cryptographically valid but not public-CA trusted; enrolment remains required.

Immutable images:

```
ghcr.io/cksidney/tibatrace-backend@sha256:54f2c42a462d64ac9d2bc3f58a8c2baec059607e752ff65f68e7887fa1c00c3b
ghcr.io/cksidney/tibatrace-hq-web@sha256:0ea2a5027fc91d46efd23094184c45ad427bebbb85f4cad5cc759140477fa414
```

## Activation and live checks

- Verified PostgreSQL custom dump, restore inventory and SHA-256 in root-only
  `/opt/tibatrace/backups/tibatrace-rc37-predeploy-20261014T011127Z` before migration.
  rc35 directory/images/runtime snapshot retained; do not revert new cash/clinical
  database facts to roll back an application.
- Four non-destructive migrations applied; `migrate --check` passed.
- Current directory:
  `/opt/tibatrace/releases/tibatrace-1.0.0-rc37-093910f5-20261014`.
- API/HQ healthy; worker/beat running and same revision; worker ping passed;
  hourly expiry schedule configured and both expiry tasks registered.
- Public health and HQ passed. `/pos/` is installer handoff. Anonymous clinical
  queue, retail transactions and installer catalogue each returned 401.
- Published final Windows kit in tenant installer catalogue, with an explicit
  platform audit entry. Authenticated handler streaming and actual HTTPS download
  each matched 107,955,670 bytes and ZIP SHA-256:
  `11b9575db8426533e24eb543ef3659f7aa36020c5e7dd846d35b5179c47bbca9`.
- [Signed Windows release](https://github.com/cksidney/TibaTrace/releases/tag/pos-windows-v1.0.5).
  Installer EXE SHA-256:
  `3f5e68edf53e69eaee918e9b4355918aef061a58da52c5e806ff5d7ac4e21284`.
- Future CI migration baseline updated to the live server revision.
- No synthetic live sales, prescriptions, refunds, stock or new credentials were
  created by activation/verification. Untracked Stage 2D.2 and user drafts preserved.

## Explicit remaining dependencies

See RC36_WORKFLOW_CLOSURE.md: 56 report packs are source-backed; 44 remain unavailable
pending their prerequisites. Providers/regulator feeds remain disabled templates.
Android release signing and installed-device acceptance remain pending. Managers
must confirm imported stock units/batches/expiry and perform real USB printer,
label, scanner and printer-connected drawer acceptance. Software checks do not
claim those physical or regulatory outcomes. VPS still needs capacity attention:
last check was approximately 1.4 GiB free (97% used); no broad project/image/volume
pruning was performed in this deployment.
