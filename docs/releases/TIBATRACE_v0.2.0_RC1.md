# TibaTrace v0.2.0-rc1

**Tag:** `tibatrace-v0.2.0-rc1`
**Branch:** `pos-windows-installer`
**Baseline:** `4b43bf8` — *Complete HQ pricing and stock transfers*
**Date:** 2026-07-31
**Status:** Release candidate. Not deployed.

---

## Executive summary

This candidate adds the enterprise reporting platform, Kenya FHIR
conformance, capability-based access control with password recovery, and a
shared design system that both POS clients and the HQ web app now render
from. It also repairs a repository that had been damaged by a Windows
filesystem round-trip.

The damage matters for reading this release. Before recovery the working
tree carried 143 modified files, 24 deleted source files, and 10,412
untracked files. Most of that was noise: one 10,351-file Windows virtualenv,
a phantom 16,534-line diff caused by CRLF conversion, and sixteen scripts
that had lost their execute bit. Underneath it was a genuine multi-workstream
body of work, which this candidate separates into reviewable commits.

Nine commits, 155 files, +16,644 / −2,632.

---

## Modules changed

| Module | Commit | Files | Summary |
|---|---|---|---|
| Repository hygiene | `93ad3417` | 2 | `.gitattributes`, `.gitignore` |
| Shared packages | `512434ff` | 10 | Money contract, layout scale, glyphs, client-version handshake |
| Backend core | `e94a1287` | 35 | `apps/core/money.py`, pricing corrections, POS serialisers |
| FHIR Kenya | `44b1137f` | 28 | IG profiles, HIE registry policy, claims IG, SMART discovery |
| Identity & Access | `bc3db7a3` | 12 | Capability catalogue, password recovery, Access workspace |
| Reports | `c81513aa` | 10 | Catalogue, PDF pipeline, QR receipts, `qrcode` dependency |
| POS Windows | `bcd2a83f` | 24 | Shared design system, responsive layout, console assertions |
| POS Android | `c0d8fd41` | 24 | Shared design system, client-version handshake, migration 0002 |
| HQ web shell | `6a210589` | 10 | Reports/Access wiring, four TypeScript fixes |

---

## Database migrations

One migration. **Non-destructive.**

`platform/0002_posrelease_client_alignment`

```python
migrations.AddField("posrelease", "minimum_supported_build",
                    models.PositiveIntegerField(default=0))
migrations.AddField("posrelease", "operations_impact",
                    models.TextField(blank=True))
```

Two additive `AddField` operations, both with defaults. No table drops, no
field removals, no data migration, no backfill. Safe to apply forward
against production without downtime.

`manage.py makemigrations --check` reports no drift.

---

## Dependency changes

**Added — Python runtime:** `qrcode==8.2`

Required by `apps/platform/reporting/pdf.py`, which
`apps/platform/reporting/services.py` imports at module scope. Without it
every report PDF download raises `ModuleNotFoundError`. Pure-python with no
transitive dependencies; the code consumes the module matrix directly and
never renders an image, so Pillow is not required. Pinned in
`backend/requirements.lock`, not the dev lock.

**JavaScript:** none. `package-lock.json` is byte-identical to the baseline,
and no `package.json` changed. An earlier incidental bump of
`@vitejs/plugin-react` to 6.0.5 was reverted; the lockfile was restored from
`HEAD` and dependencies reinstalled with `npm ci`, which resolves strictly
from the lockfile without re-resolving ranges.

---

## Breaking changes

**Money serialisation now renders two decimal places everywhere.**

`amount_remaining` previously serialised an exact zero as `"0"` while its
sibling fields `amount_due` and `amount_settled` serialised `"150.00"`. Every
monetary field now routes through `apps.core.money.format_money`, so an exact
zero serialises as `"0.00"`.

Any client parsing these fields with an exact string comparison against `"0"`
will need updating. Numeric parsers are unaffected. The frontend counterpart,
`packages/shared/src/money.ts`, applies the same rule, so POS terminals and
the HQ web app agree.

**Pricing no longer auto-creates a `CommercialSKU`.**

Uncommitted work had added a path that manufactured a tenant SKU from a
global government master during a set-price call. It was removed. The path
could never have succeeded — `manufactured_product` and `package_definition`
are non-nullable `PROTECT` foreign keys and neither was supplied — so no
deployed behaviour changes. The pre-existing contract is restored: product
and package governance must complete before an item can be priced, enforced
by `ValidationError`.

---

## Demo seed safety

Two seed commands create privileged accounts — `seed_pos_dispensing_demo`
(pharmacist, cashier, **CDS approver**) and `seed_hq_workspaces` (HQ operators,
managers, approvers across every active tenant). Both are now fail-closed.

**Blocked in production.** Both refuse when `settings.DAWATRACE_ENV` resolves to
`production`, `prod` or `live`. The comparison is case-insensitive and
whitespace-stripped. Neither `--allow-demo-seed` nor `DEBUG=True` overrides this
— the environment check is evaluated first and has no escape.

Outside `DEBUG`, running either command additionally requires an explicit
`--allow-demo-seed` flag, so a staging run is a deliberate act.

**Passwords are no longer hardcoded or logged.** The two retired demo
credentials are removed from tracked source — and from Git history, which was
rewritten before the first push so they appear in no reachable commit. A
regression test asserts they cannot reappear anywhere under `backend/`.

The same credential was also prefilled into the POS demo login form in
`backend/static/pos/js/pos.js` — a `value="…"` on a password input, plus a
sign-in hint naming it. That file is in `STATICFILES_DIRS`, so it was collected
by `collectstatic` and served publicly at `/static/`. Both are removed; the
field now renders empty and the hint names only the username.
Credentials now come from `DAWATRACE_DEMO_SEED_PASSWORD`, validated through
Django's `validate_password`. When that variable is absent, a cryptographically
random 24-character password is generated — but only under `DEBUG`, or when
`--allow-demo-seed` has already established non-production intent.

A supplied password is **never** echoed. A generated password is shown exactly
once, and only under `DEBUG`, labelled local-development-only. Command output
still reports usernames, roles and tenant, plus whether the password was
supplied or generated.

### Required local-development invocation

```bash
export DAWATRACE_DEMO_SEED_PASSWORD='choose-a-strong-local-password'
python manage.py seed_hq_workspaces --tenant <slug>
python manage.py seed_pos_dispensing_demo --tenant <slug>
```

With `DEBUG=True` the variable may be omitted and a random password is printed
once. Outside `DEBUG`, add `--allow-demo-seed` and set the variable if you need
a password you can actually log in with.

### Environment-variable requirements

| Variable | Required when | Notes |
|---|---|---|
| `DAWATRACE_ENV` | always (defaults to `development`) | `production`/`prod`/`live` blocks all demo seeding |
| `DAWATRACE_DEMO_SEED_PASSWORD` | outside `DEBUG` when a usable password is needed | Validated by Django; never printed |

### Security-test evidence

`backend/tests/test_demo_seed_safety.py` — **30 tests**, covering: refusal in
each production alias for both commands; `--allow-demo-seed` failing to override
production; `DEBUG=True` failing to override production; case and whitespace not
bypassing the guard; refusal outside `DEBUG` without the flag; successful local
run; missing password variable failing safely; weak supplied password rejected;
generated password confined to `DEBUG`; generated passwords not repeating; a
supplied password never appearing in captured output; idempotency across two
runs with no duplicate users or role assignments; existing users reused rather
than duplicated; retired literals absent from tracked source; and every
password-setting seeder invoking the shared guard.

The repository secret scanner (`scripts/scan_secrets.py`) gained four rules for
the classes it previously missed — `password-constant`, `set-password-literal`,
`create-user-password-literal` and `printed-credential` — with a documented
test-only exemption by location. Verified by reintroducing the retired literals
and confirming detection, then removing them again. **Tracked-source findings: 0.**

## Upgrade notes

1. Install the new runtime dependency: `pip install -r backend/requirements.lock`.
   The report download endpoints will 500 without `qrcode`.
2. Apply `platform/0002`. Additive only; no downtime required.
3. No `.env` changes. No new environment variables.
4. No changes to PostgreSQL, Redis, MinIO, or media volume configuration.
5. Deployments that build the Android client should note the native project
   under `apps/pos-android/android/app/src/main` was restored in `93ad3417`.
   Any branch cut from the damaged tree is missing it.

---

## Known limitations

**Reports verification is partial.** Server-side PDF export is covered
end-to-end, including uniqueness of the QR validation receipt, and the
`#reports` navigation guard passes. The following were **not** verified,
because they require a running authenticated instance with production-shaped
data:

- report filters and date filters
- tenant isolation in the reporting surface
- branch and warehouse scoping
- Excel/CSV export
- background report generation
- scheduled report job queuing
- report access permission enforcement

**A security exemption was added and needs ratification.** Password recovery
resolves a user by primary key without tenant qualification, which the
tenant-safety audit flags. The exemption is documented in
`apps/prescription/management/lookup_safety.py` and confined to
`identity/api/session_views.py` by module binding — pasting the marker
elsewhere still fails the audit, verified against a probe. The rationale is
that a reset link exists before any tenant context, and `check_token`, bound
to the user's pk, password hash and `last_login`, is the actual access
control. This is a security decision and should be reviewed by whoever owns
that audit.

**`npm audit` reports 28 vulnerabilities (27 high, 1 critical)** in the
dependency tree. These pre-date this candidate and were not introduced by it.
Not triaged here; addressing them would have meant dependency changes outside
the scope of this release.

**Eight `.sh` files under `node_modules` are non-executable.** These ship that
way from their upstream tarballs (iOS, Linux and 7zip helpers unused by this
build) and are not residual contamination.

---

## Validation evidence

All figures from a clean run after `npm ci`.

| Check | Result |
|---|---|
| Backend `pytest` | **1,437 passed**, 0 failed |
| Frontend tests | **348 passed**, 0 failed |
| — `@dawatrace/shared` | 175 |
| — `@dawatrace/hq-web` | 43 |
| — `@dawatrace/pos-android` | 38 |
| — `@dawatrace/pos-windows` | 92 |
| TypeScript | **exit 0**, all 4 workspaces |
| Builds | **clean**, all 4 workspaces |
| `manage.py check` | 0 issues |
| `makemigrations --check` | No changes detected |
| Android `assembleDebug` | **BUILD SUCCESSFUL**, 35 MB APK, 10 launcher icons packaged |
| Infrastructure security | 33 passed |
| Demo seed safety | 30 passed |
| Reports PDF | 2 passed |
| HQ reports navigation | passed |
| Restored medicines tests | 21 passed |

Baseline before recovery: 1,394 backend passed / 6 failed, 347 frontend
passed / 1 failed, 4 TypeScript errors, Android unbuildable.

---

## Rollback procedure

Nothing has been pushed or deployed. All rollback is local.

**Discard the entire release series, returning to the baseline commit:**

```bash
git reset --hard 4b43bf8
```

This discards all nine commits and every recovery change. The restored
Android native project and medicines tests return to their committed state
at `4b43bf8`, where they are intact — the deletions were never committed.

**Discard the tag only:**

```bash
git tag -d tibatrace-v0.2.0-rc1
```

**Roll back a single workstream**, leaving the rest intact:

```bash
git revert --no-commit <commit-sha>
```

**Database rollback**, if `platform/0002` has been applied and must be undone:

```bash
python manage.py migrate platform 0001
```

Both added fields are nullable-by-default and carry no data, so reversing is
safe. This is the only migration in the release.
