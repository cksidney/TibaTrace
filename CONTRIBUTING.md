# Contributing

1. Work from a reviewed branch and keep changes within one bounded context.
2. Do not add dependencies on Mercato source paths, tables, credentials or queues.
3. Preserve tenant scope at model, service, API, task and FHIR boundaries.
4. Add tests for behavior, tenant isolation, failure handling and idempotency.
5. Do not add clinical content without source, licence and clinical approval.
6. Run `./scripts/validate_repository.sh --full` before requesting review.
7. Do not claim Firely compatibility, FHIR portability or production readiness
   without the corresponding approved evidence.
