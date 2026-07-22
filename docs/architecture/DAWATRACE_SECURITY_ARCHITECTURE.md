# DawaTrace Security Architecture

## Tenant Isolation

Tenant-bearing models use `StrictTenantManager`, `ClinicalKnowledgeManager`, or
`TerminologyManager`. With no active tenant these managers return no rows. Services
that use `all_objects` must include tenant in the same query. The one reviewed
manager exception is `identity.User`, required to authenticate before tenant
middleware; capability checks remain tenant-qualified.

## Authorization

RBAC grants named capabilities through active tenant roles. Matching ABAC deny
policies override grants. Platform administration is explicit, not inferred from
missing tenant data. Clinical overrides require capability and reason; prohibited
findings cannot be overridden.

## Clinical Safety

Missing or failed clinical knowledge returns `KNOWLEDGE_UNAVAILABLE` or `ERROR`,
never `PASS`. Prescription payment and dispense cannot bypass clinical review or
use a stale context hash. Provider adapters fail closed until configured.

## Documents and Secrets

Object keys begin with `tenant/<uuid>/`; canonical path resolution blocks
traversal. Uploads enforce type, extension, size, SHA-256, and a malware-scanner
integration result. Signed tokens bind document, tenant, actor, and age. Every
successful or failed-integrity access is audited. Production settings reject
default secrets and enable secure cookies, TLS redirect, HSTS, nosniff, and frame
denial. No production secret is stored in the repository.

## Verification Controls

- AST unsafe UUID lookup audit: zero unreviewed findings.
- tenant manager audit: 54 models, zero unreviewed findings, one approved user exception.
- Bandit: zero findings over 10,612 lines.
- local committed-secret scan: zero findings.
- production-template `check --deploy`: zero issues.
- document authorization/integrity tests: passing.

Online advisory lookup and history-aware secret scanning remain external CI gates.
