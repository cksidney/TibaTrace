# DawaTrace Dependency Map

## Internal Direction

```text
core <- tenancy <- identity
core <- organizations <- practitioners
core <- patients
core <- medicines
patients + practitioners + organizations + medicines <- prescription
patients + practitioners + prescription <- clinical
patients + prescription + medicines <- cds
clinical + prescription + terminology + audit <- fhir
patients + identity <- documents
tenancy <- audit/workflows/notifications/crosswalks
```

`apps.fhir` is an adapter boundary and must call domain services for writes. It is
not the owner of patient or clinical state. `apps.prescription.services.clinical_domain`
is a compatibility import only; the implementation is in `apps.clinical.services`.

## External Runtime Dependencies

PostgreSQL, Redis, object storage, and optional provider endpoints are configured
with `DAWATRACE_*` settings. Default provider adapters are deliberately
unconfigured and return unavailable/false; no source test adapter reports a
successful external verification.

## Removed Source Coupling

There are no imports from Mercato `pharmacy`, `catalog`, `inventory`, `sales`,
`users`, `common`, or `events` apps. There are no relative paths, symlinks,
cross-database foreign keys, shared queues, or shared object roots.

Historical `mercato-os.com` FHIR identifier/profile URIs remain only as immutable
interoperability lineage in the copied conformance artifact and prescription
identifier systems. They do not perform network access.

## Explicit Extraction Divergence

The unwired legacy prescription plugin subtree was omitted because it imported
knowledge models absent from the canonical schema and duplicated `apps.cds`.
The provider-based, source-attributed CDS engine is the only Phase 2 clinical
decision implementation. Restaurant, Factory, Retail, Forecourt, OMS, loyalty,
finance, procurement, and POS code were not copied.
