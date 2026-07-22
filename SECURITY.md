# Security Policy

## Supported Versions

Phase 2 is an extraction foundation and is not approved for production use.

## Reporting

Report suspected vulnerabilities privately to the Esenai Group Ltd security
owner. Do not place patient data, credentials, tokens or exploit details in a
public issue.

## Baseline Controls

- explicit tenant ownership and fail-closed managers
- tenant-qualified UUID and FHIR reference resolution
- capability checks for clinical and FHIR operations
- redacted audit and error responses
- independent secrets, database, Redis and object-store namespaces
- immutable legacy identifier crosswalks
- authorized, expiring clinical-document download grants
- locked FHIR R4 dependency versions

See `docs/architecture/DAWATRACE_SECURITY_ARCHITECTURE.md` for threat boundaries
and the latest generated security evidence under `artifacts/generated/security/`.
