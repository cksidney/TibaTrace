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
