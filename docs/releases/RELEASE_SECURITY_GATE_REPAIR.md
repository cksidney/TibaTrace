# Release security gate repair — held before deployment

Production remains rc37. rc43 publication/CI and the separately dispatched
production-major parity run were canceled before image publication or activation
when online dependency audit found 13 known advisories in three pinned packages.
The focused PostgreSQL workflow fixes are retained, but this is not a complete
passing release or a certification that those fixes are live.

## Publisher-supported dependency repairs

- Django 5.1.15 is unsupported. Upgrade to supported 5.2 LTS patch **5.2.18**;
  see [support policy/version](https://www.djangoproject.com/download/) and
  [5.2.18 notes](https://docs.djangoproject.com/en/5.2/releases/5.2.18/).
- DRF **3.18.3** includes parser-size and permission-preserving admin-rendering
  repairs plus the newer large-Accept-header/charset hardening. See the
  [publisher release notes](https://www.django-rest-framework.org/community/release-notes/).
- cryptography **50.0.2** includes the reviewed PKCS7 and certificate-chain fixes
  and updated wheels; see [publisher changelog](https://cryptography.io/en/latest/changelog/).

The revised complete Python dependency audit reports no known vulnerabilities.
All 168 focused business/governance tests pass on PostgreSQL with these upgrades.
Four new request-boundary tests verify that oversized JSON/form bodies return
413 before business processing without body echo; small requests still work; and
invalid AdminRenderer writes cannot invoke a GET denied by permissions. Schema
checks find no additional model migration.

## Exact container evidence

The old HQ image's SBOM, explicitly identified as Alpine 3.21.3, reports 16 high
advisories. An unsupported-OS scan without that identification was rejected as
inconclusive, not counted as a pass. The updated official nginx slim base removes
unused image/font libraries; its remaining PCRE2 and zlib fixes are pinned.

The current Debian Python base still reports high/critical runtime findings,
including unfixed packages. A pinned official minimal Python Alpine base with
reviewed zlib and packaging-tool updates is under clean container compatibility
validation. PostgreSQL drivers, reporting imports, non-root operation, full
migrations and health endpoints must pass; changing a base is not proof of safety.

CI's container-scan reminder is replaced by actual pinned Trivy scans. The gate
requires Linux amd64, the expected image/source label, supported OS package
inventory and the backend's application dependencies. It rejects all HIGH or
CRITICAL findings, including unfixed advisories; no ignore-unfixed, .trivyignore,
model exemption or empty/unknown inventory can produce a pass. Nonblocking
findings remain visible in JSON evidence. Online Python auditing is required
before publication; a skipped advisory step cannot be presented as validation.

Full new-source SQLite/production-major PostgreSQL regression, application gates,
complete image scans, provenance, backup and live checks remain pending.

The first non-publishing preflight built both images successfully, then correctly
blocked the backend scan on four findings in pip's bundled msgpack/setuptools/
urllib3. The installed application urllib3 was already patched; the bundled copy
was distinct. Final runtime images now remove pip, setuptools and wheel after
installation, including both interpreter environments, instead of hiding or
rewriting their vulnerability metadata. Application urllib3 is explicitly pinned
to 2.8.0. A fresh complete scan and runtime smoke are still required.
