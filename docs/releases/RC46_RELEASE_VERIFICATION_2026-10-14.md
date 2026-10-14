# rc46 deployment verification — 14 October 2026

Status: deployed; activation and live permission checks passed.

Runtime source: `cfee05110cb0e289f751f7a79ac2e9fc451129e5`.
Tag: `tibatrace-v1.0.0-rc46`. Previous live/rollback source is rc44,
`19007332d078f1dbff5e033bffae9ce4963d73d0`. GitHub main was checked again before
activation and contains no commits ahead of this candidate. The rc45 candidate
was cancelled before image activation and its immutable tag remains history.

## Final-source release evidence

[Production Images run 38562674412](https://github.com/cksidney/TibaTrace/actions/runs/38562674412)
passed all required gates:

- Full migrated SQLite suite: **2,172 passed**, zero failures/errors/skips.
- Full PostgreSQL suite: **2,172 passed**, zero failures/errors/skips. Independent
  `source-database.json` verification confirms the runtime Django vendor,
  PostgreSQL **16.15**, and the exact source above.
- Backend Ruff, Django checks, migration drift and clinical lookup audit passed.
  The online pinned dependency audit has zero findings.
- Clean-checkout HQ/shared/Windows/Android type checks, production bundles and
  unit tests passed: **82 / 211 / 106 / 41**, respectively (**440 total**).
- Both complete Trivy runtime reports were revalidated locally against the
  exact revision, Linux amd64, supported OS and actual package inventories.
  Both have zero vulnerability findings, with no suppression/ignore-unfixed.
- Eleven release-evidence file checksums passed; manifest revision, version,
  tag, architecture and deployment baseline match. Both GitHub image provenance
  verification commands exited successfully. SBOMs and migration evidence are
  retained with the run.

There are non-blocking GitHub runner/action runtime migration notices in the
run; these are not test failures or audit findings. This was not a new native
hardware or physical printer acceptance run.

Additional local evidence: 102 targeted migrated server tests; synthetic browser
checks at 1440px desktop and 390px mobile, plus owner-in-selected-tenant scope,
passed without runtime errors. These browser fixtures are explicitly separate
from the real live account checks below.

## Activation

Verified immutable images:

```
ghcr.io/cksidney/tibatrace-backend@sha256:ff0867cbb2cab826071bd435f70bb76c2e598513ec338e5ce1ebafe2d55192a3
ghcr.io/cksidney/tibatrace-hq-web@sha256:61f57cfa3b72b3f373bc8c2590f1695faae1a10a37d4842fbbf96d11a7585d47
```

Deployment archive SHA-256:
`c13821edf7f3b71409f7af61c4a666a808f5af46a24177ad845e12f763159a9e`.
The archive contains only VERSION, deployment configuration and release notes;
runtime source is carried by the verified CI images, not a laptop source copy.

Fresh pre-deploy PostgreSQL custom dump, restore inventory and SHA-256 check:
`/opt/tibatrace/backups/tibatrace-rc46-predeploy-20261014T132550Z`.
Directory mode 700; dump and production environment mode 600. Backup and rc44
images/source remain retained. No database restore or app rollback was needed.

The migration command used bounded lock/statement timeouts and reported no
migrations to apply. API/HQ are healthy; worker/beat are running, all four at
the source above. PostgreSQL/runtime/version checks, Django system checks,
worker ping and public HTTPS health passed. The active pointer is:
`/opt/tibatrace/releases/tibatrace-1.0.0-rc46-cfee0511-20261014`.

Activation log: `/opt/tibatrace/releases/rc46-activation.log`.
VPS headroom after activation: approximately 2.5 GiB free, 94% used. No broad
cleanup or removal of unrelated applications/data occurred in this task.

## Actual live permission verification

- Read-only audit of all **21 active tenant identities** found no explicit
  platform-admin/superuser flags. Fresh navigation policy excludes all four
  owner-only views for every tenant identity. Both actual active owner identities
  retain those views. No role, ownership flag or access grant was altered.
- An existing tenant account that had completed its password gate passed
  authenticated HTTPS overview/session verification: 11 permitted modules,
  explicit non-owner identity, and only permitted overview links. All five
  national owner endpoints (providers, activations, evidence, reports, recalls)
  returned **403**. A different tenant header was also refused with **403**.
  This is one actual tenant HTTPS scenario, not a claim that all 21 accounts
  have completed login acceptance; their current policy was separately checked.
- An existing owner passed authenticated HTTPS verification both globally and
  inside a selected active tenant, retaining owner navigation in both cases.
- HTTPS HQ returned 200 and serves `/assets/index-d3qmuDwL.js`, including the new
  access policy. Bundle SHA-256:
  `2bb7c1743ab018955e3ffb8930a3da95cef18b7112ffbad3f0f1df851816a7be`.
  HTML advertises `no-store, no-cache, must-revalidate`. Already-open tabs still
  need a page reload to execute the new bundle.
- Signed managed Windows POS 1.0.5 publication metadata remains unchanged,
  with the previously verified 107,955,670-byte ZIP and SHA-256
  `11b9575db8426533e24eb543ef3659f7aa36020c5e7dd846d35b5179c47bbca9`.
  No native/shared source differs from its signed source. No new installer was
  published; Android signing and Manager stock/hardware acceptance remain
  separate pending checks.

The live verifier streamed through stdin to preserve the container's read-only
filesystem after an initial `docker cp` attempt was correctly refused. Local
HTTPS asset verification used the installed CA bundle after the host Python
default trust path lacked issuers; TLS verification was never disabled.
No temporary credentials were saved or printed. In-memory, short-lived bearer
tokens used existing identities, and no password, access grant, stock, sale or
prescription was created for verification.

Live check log: `/opt/tibatrace/releases/rc46-live-permission-check.log`.
Local retained release evidence:
`/private/tmp/tibatrace-rc46-evidence.Q5zHRh`.

## Scope

Owner-only sidebar, command search, shortcuts, account links, global regulator
register and forbidden hash routes are hidden/blocked for tenants. Tenant
workflows, tenant users/access and recall response remain governed by existing
effective capabilities. Menu filtering is not API authority: the explicit owner
and tenant/capability API guards remain enforced. This is a targeted permission
and navigation fix, not certification of every business workflow or integration.

Untracked prototypes, user documents and other worktrees remain untouched.
