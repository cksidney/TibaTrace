# TibaTrace Release Packaging Workflow

**Status:** Proposed. No established workflow was recovered — see *Findings*.
**Applies to:** `tibatrace.esenai.co.ke` on `159.69.34.39`, deployment root `/opt/tibatrace`.

---

## Findings: what actually happened for releases 62f74e7 → 24a1602 → 92282eb

I looked for an established process — packaging scripts, CI jobs, rsync/scp
wrappers, manifests, tag conventions — and found none that produces
`releases/<version>-<sha>-<timestamp>/`. The evidence says these bundles were
assembled by hand:

| Evidence | What it shows |
|---|---|
| Release dirs contain `debug_test.py`, `fix_tests.py`, `extra_alloc.py`, `extra_models.py`, `extra_services_2.py` | Whole-repo copies, not curated bundles |
| Ownership `UNKNOWN:staff` (uid 501, gid `staff`) on `24a1602` and `62f74e7` | Copied from a macOS machine via `scp`/`rsync` as a non-root user |
| Only metadata file is `VERSION` (`0.1.0-alpha.1`) | No manifest, no commit SHA, no build timestamp, no checksums, no SBOM |
| `tibatrace-hq-web:…-92282eb-…` carries `revision=unknown`, `created=unknown` | Built without `--build-arg SOURCE_REVISION/BUILD_TIME`; an ad-hoc `docker build` |
| `tibatrace-backend:…-24a1602-…` carries `revision=24a1602141145…` | That one *was* built with the documented build args — inconsistent practice |
| No registry prefix on any image tag; no `docker save`/`load` artefacts | Images are built **on the production VPS** from the uploaded source tree |
| `scripts/` contains only `package_pos_android_release.sh`, `package_pos_windows_release.sh`, `package_pos_windows.ps1` | Packaging exists for POS clients only, never for the server |
| `.github/workflows/` has `ci.yml`, `fhir-*.yml`, `windows-release.yml` | CI tests and packages the Windows POS; it does not build or publish server images |
| `Makefile` `docker-build` target tags `dawatrace/backend:phase3` | A stale local-dev target, unrelated to production tags |

Building images on the VPS is the root cause of the disk-headroom problem: the
backend and HQ builder stages compete for space with five other production
applications on a single 38 GB filesystem.

### Answers to the ten discovery questions

1. **Where images are built** — on the production VPS, from the uploaded source tree.
2. **Local, CI, or VPS** — VPS. CI never builds server images.
3. **Registry or tar** — neither. Local `docker build`, local tags, no registry, no `docker save`.
4. **How `releases/<version>-<sha>-<ts>/` is created** — manual `scp`/`rsync` of a whole working tree, directory named by hand.
5. **Which files belong in the bundle** — undefined. Current bundles carry the entire repository including scratch files.
6. **How production `.env` is referenced** — `deploy-server.sh` takes `$1` or defaults to `<script_dir>/.env.production`; in practice the compose project is invoked with `--env-file /opt/tibatrace/secrets/.env.production`. The env file lives outside the release dirs and survives releases.
7. **How `current` is changed** — manually repointed (`current -> releases/…-92282eb-…`). Nothing automates it, and nothing verifies the running containers match it.
8. **How rollback works** — implicitly, by repointing `current` and re-running compose with an older `DAWATRACE_IMAGE`. Undocumented and untested.
9. **How migrations are applied** — `deploy-server.sh` runs `docker compose --profile maintenance run --rm migrate` before starting services.
10. **How image integrity is verified** — it is not. No checksums, no signatures, no SBOM.

---

## Proposed workflow

Designed to fix the three defects above: build off-host, produce a verifiable
bundle, and make activation and rollback explicit. **Not yet executed.**

### 1. Build off-host

Build on the developer Mac, a clean Linux builder, or CI — never on the
production VPS while headroom is under 10 GB.

```bash
git fetch --tags origin
git checkout tibatrace-v0.2.0-rc1
SHA=$(git rev-parse HEAD)          # must equal 95c90243ec768c4d18ee4da29bfad48e4b2500f3
SHORT=$(git rev-parse --short=7 HEAD)
VERSION=$(cat VERSION)
TS=$(date -u +%Y%m%dT%H%M%SZ)
TAG="${VERSION}-${SHORT}-${TS}"

docker build --file docker/backend.Dockerfile \
  --build-arg DAWATRACE_VERSION="$VERSION" \
  --build-arg SOURCE_REVISION="$SHA" \
  --build-arg BUILD_TIME="$TS" \
  --tag "tibatrace-backend:${TAG}" .

docker build --file apps/hq-web/Dockerfile \
  --build-arg DAWATRACE_VERSION="$VERSION" \
  --build-arg SOURCE_REVISION="$SHA" \
  --build-arg BUILD_TIME="$TS" \
  --tag "tibatrace-hq-web:${TAG}" .
```

Both `--build-arg SOURCE_REVISION` values are mandatory. An image whose
`org.opencontainers.image.revision` reads `unknown` must never reach production —
that is exactly how the current ambiguity arose.

### 2. Assemble the bundle

The bundle carries only what deployment needs, not the working tree:

```
tibatrace-<TAG>/
├── RELEASE_MANIFEST.json      # version, git SHA, tag, build time, image digests
├── VERSION
├── deploy/tibatrace/          # compose files, deploy-server.sh, Caddyfiles, README
├── images/
│   ├── tibatrace-backend-<TAG>.tar.zst
│   └── tibatrace-hq-web-<TAG>.tar.zst
├── migrations/PLAN.txt        # output of `migrate --plan` from the release image
├── sbom/dawatrace-backend.cdx.json   # `make sbom`
├── SHA256SUMS
└── ROLLBACK.md
```

`RELEASE_MANIFEST.json` must record `git_sha`, `git_tag`, `version`,
`build_time`, both image tags, and both image digests
(`docker image inspect --format '{{index .RepoDigests 0}}'` or the local
`Id` when there is no registry).

### 3. Checksum and sign

```bash
( cd "tibatrace-${TAG}" && find . -type f ! -name SHA256SUMS -print0 \
    | sort -z | xargs -0 sha256sum > SHA256SUMS )
```

Sign `RELEASE_MANIFEST.json` with the repository's approved signing mechanism.
**Do not** sign with `TIBATRACE_RELEASE_SECRET_KEY` — despite its name, that is
the MinIO/S3 *secret access key* used by `boto3` to presign installer
downloads (`backend/apps/platform/release_storage.py`), not an artefact signing
key. The document/object signing key is `DAWATRACE_OBJECT_SIGNING_KEY`, which is
a separate secret and must not be reused for release signing either.

### 4. Transfer and verify

```bash
tar -I 'zstd -19' -cf "tibatrace-${TAG}.tar.zst" "tibatrace-${TAG}"
sha256sum "tibatrace-${TAG}.tar.zst"                       # record locally
scp "tibatrace-${TAG}.tar.zst" root@159.69.34.39:/opt/tibatrace/incoming/
```

On the host, verify **before** unpacking, then verify the inner checksums:

```bash
cd /opt/tibatrace/incoming
sha256sum -c <<< "<recorded-sum>  tibatrace-${TAG}.tar.zst"
tar -I zstd -xf "tibatrace-${TAG}.tar.zst" -C /opt/tibatrace/releases/
cd "/opt/tibatrace/releases/tibatrace-${TAG}" && sha256sum -c SHA256SUMS
```

### 5. Load images

```bash
zstd -dc images/tibatrace-backend-${TAG}.tar.zst  | docker load
zstd -dc images/tibatrace-hq-web-${TAG}.tar.zst   | docker load
docker image inspect "tibatrace-backend:${TAG}" \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

The printed revision must equal the release SHA. Delete the `.tar.zst` files
from `incoming/` once loaded, to return the space.

### 6. Activate

Activation is a deliberate, separate step. Update `DAWATRACE_IMAGE` and
`TIBATRACE_HQ_IMAGE` in `/opt/tibatrace/secrets/.env.production` (backing the
file up first, preserving mode 600), repoint `current`, then:

```bash
cd /opt/tibatrace/current/deploy/tibatrace
./deploy-server.sh /opt/tibatrace/secrets/.env.production
```

That script validates the composed config, runs the `migrate` maintenance
profile once, brings up `redis api worker beat hq`, and prints `ps`.

**Invariant that would have prevented the current ambiguity:** after every
deployment, assert that `current`, `DAWATRACE_IMAGE`, `TIBATRACE_HQ_IMAGE` and
every running container's `org.opencontainers.image.revision` all resolve to the
same commit. Any drift is a failed deployment, not a partial success.

### 7. Rollback

Keep at least one prior release directory and its images. To roll back: restore
the previous `.env.production` from `/opt/tibatrace/secrets/`, repoint `current`
to the previous release directory, and re-run `deploy-server.sh`. Migrations are
**not** automatically reversed — check `ROLLBACK.md` in the bundle for whether
the release's migrations are backward-compatible with the previous image before
rolling back.

---

## Why clean container builds are mandatory

The v0.2.0-rc1 release was blocked by a defect that every local check passed.

`apps/hq-web/Dockerfile` copied `packages/shared/package.json` but never the
package's source, and never built it. `hq-web` imports
`@dawatrace/shared/money.js`, which the exports map resolves to
`packages/shared/dist/money.js` — and `dist/` is gitignored, so it does not
exist in a container. The build failed with
`Rolldown failed to resolve import "@dawatrace/shared/money.js"`.

The Dockerfile had always been incomplete. This release was simply the first to
import a shared subpath. What hid it was **stale local artefacts**: `npm run
build` succeeded on a developer machine because an earlier run had left
`packages/shared/dist` on disk. `scripts/validate_workspaces.sh` compounded it
by building `apps/` before `packages/` — it sorted both trees together and
`apps` sorts first — so even a full workspace build never produced the shared
package first.

Three rules follow, and they are now enforced rather than advisory:

1. **A release is only buildable if it builds in a clean container.** Workspace
   builds are a development convenience; they are not release evidence.
   `.github/workflows/production-images.yml` builds both server images from a
   clean checkout for `linux/amd64` on every pull request, on `main`, and on
   every `tibatrace-v*` tag.
2. **Generated output must never enter the build context.** `.dockerignore`
   excludes `apps/**/dist` and `packages/**/dist`, so the image builds the
   shared package itself instead of inheriting whatever a developer left behind.
3. **Every release image must carry its exact revision.** CI fails the build if
   `org.opencontainers.image.revision` is empty or `unknown`. The HQ image
   currently in production reports `unknown`, which is precisely how the
   provenance of a running component became unverifiable.

## Retention policy

Keep the running release plus one prior release (directory *and* both images).
Anything older is removable. Never delete `/opt/tibatrace/backups`,
`/opt/tibatrace/secrets`, or any Docker volume.
