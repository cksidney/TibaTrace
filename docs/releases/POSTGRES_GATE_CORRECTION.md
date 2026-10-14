# PostgreSQL validation provenance correction — 14 October 2026

`ci.yml` provisions PostgreSQL, but `validate_repository.sh` sets
`DAWATRACE_DATABASE_URL` to its local SQLite validation file before migrations and
pytest. The job cannot be cited as a PostgreSQL business-suite result. Previous
rc37 documentation has been corrected; successful production migration/health
checks are still valid but are not a substitute for PostgreSQL regression.

The separate PostgreSQL release-validation workflow checks out a caller-specified
immutable release ref, verifies the exact full expected source SHA, asserts the
actual Django connection vendor is `postgresql`, records the server version,
applies migrations and runs the entire backend suite directly. It does not invoke
the script that overrides the URL. Evidence includes database/source identity and
JUnit results; a job merely provisioning a database is not sufficient.

For rc40 the workflow configuration may be on a later evidence-only commit, but
the tested application checkout must equal `80946fda4ffc4e8b565967d60e0f895ba9235c0e`.
The exact tested runtime source is recorded separately from workflow dispatch SHA.
Activation remains withheld until real PostgreSQL and the other release gates pass.

Future CI runs invoke the separate PostgreSQL job alongside SQLite repository
validation. Future production-image workflows require both PostgreSQL and quality
jobs before image publication. rc40 uses its already immutable runtime/tag with
an additional exact-source PostgreSQL run; no existing tag was moved.
# Production-major parity confirmation, 14 October 2026

The live VPS reports PostgreSQL 16.15. The first new regression runs used 18.6;
their exact vendor/version evidence is retained and must not be labelled as
production-major acceptance. The reusable gate now defaults to PostgreSQL 16.
rc43 also requires a separately dispatched full PostgreSQL 16 run checking out
its immutable runtime source `166e512cd00cc76f1244d7eec8e6caf166577152`.
This validation change does not upgrade or mutate the live PostgreSQL service.

