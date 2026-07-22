# DawaTrace Phase 2 Source Baseline

## Baseline Identity

| Field | Recorded value |
| --- | --- |
| Source repository | `/Users/sidneykibet/RetailOS` |
| Source commit | `5c84ad1781d843654b4bc446466384fee18394f1` |
| Branch | `main` |
| Extraction manifest timestamp | `2026-07-22T12:47:23.440271+00:00` |
| Source tree clean | No |
| Modified or staged paths | 112 |
| Untracked paths | 1,212 |
| Selected extraction files | 225 |
| Release tag created | No |

The commit does not, by itself, represent the complete healthcare baseline.
Several Pharmacy, prescription, FHIR, migration, test and documentation files are
untracked. Their working-tree bytes are recorded individually in the source
manifest. No claim is made that the source repository is clean or release-ready.

## Source Manifest

Machine-readable manifest:

Source copy in this standalone repository:

`artifacts/source/source_manifest.json`

The original Mercato metadata remains at
`artifacts/dawatrace_phase_2/source_manifest.json` in the source repository.

Manifest SHA-256:

`6bf858c24d4e2248e66f44e3e9eabe9b1a3fe723b8b5b9b9aa7114f1d7352f46`

For each selected file the manifest records:

- source path
- working-tree SHA-256 and byte size
- source Git state (`tracked_clean`, `modified`, or `untracked`)
- Phase 1 classification
- intended DawaTrace path or transformation target

It also contains the complete porcelain Git status at generation time. This is
deliberately verbose so later review can distinguish committed source from
unreviewed working-tree content.

## Runtime and Dependency Baseline

Observed host tools:

| Tool | Version |
| --- | --- |
| Python | 3.11.3 |
| Node.js | 20.20.0 |
| Docker | 29.2.1 |
| PostgreSQL client | 18.1 |

Source service assumptions in Mercato Compose:

- PostgreSQL: `postgres:18-alpine`
- Redis: `redis:7-alpine`

Required healthcare runtime declared in `backend/requirements.txt`:

- Django 5.1.15
- Django REST Framework 3.15.2
- fhir.resources 6.5.0
- Pydantic 1.10.26
- Celery 5.4.0
- redis-py 5.2.0
- psycopg 3.2.3

The pre-existing `/Users/sidneykibet/venv` contains Django 4.2.11, despite the
source requirement of Django 5.1.15. It is not accepted as the DawaTrace build
environment. Phase 2 uses a clean, independently installed environment.

## Selected Source Boundary

The manifest selects the validated prescription and FHIR implementation, clinical
domain service, terminology, CDS/plugin infrastructure, source healthcare tests,
certification scripts and narrowly required platform primitives.

Mixed Mercato platform code is classified as transformation input rather than a
wholesale copy. Pharmacy DUR and catalogue sources are recorded as behavioral and
schema references for the DawaTrace CDS and medicines contexts.

Explicitly excluded runtime domains are Restaurant, Factory, Forecourt, general
Retail, Wholesale, loyalty and OMS.

## Freeze Controls

1. No source release tag was created because the tree is dirty and unreviewed.
2. No production data, database, migration or deployment was touched.
3. Existing Mercato modifications and untracked files were not reverted.
4. The DawaTrace repository must record this source commit and manifest digest in
   its extraction metadata.
5. Any later source refresh requires a new manifest and full behavioral rerun.

## Review Blocker

Before a production migration or certification release, the intended Mercato
healthcare source must be committed on a reviewed branch and tagged. Phase 2 can
create and validate an independent repository from the recorded bytes, but this
dirty source state remains a provenance blocker for a production release.
