# Kenya Data Protection Act, 2019 — FHIR / HIE compliance map

TibaTrace / DawaTrace treats health data as sensitive personal data under the
**Data Protection Act, 2019** (and aligns with Digital Health Act 2023 / DHA IG
security guidance). This is an engineering control map — not legal advice.

## Act principles → product controls

| Principle / duty | Product control | Status |
|------------------|-----------------|--------|
| Lawfulness / purpose limitation | Tenant-scoped FHIR APIs; PHI without auth forbidden (metadata + SMART discovery excepted) | Met (gateway) |
| Data minimisation | POS / patient serializers strip sensitive fields without capability; FHIR converters should omit free-text narrative beyond clinical need | Partial |
| Confidentiality / integrity | TLS in production; encrypted patient identifiers (`PATIENT_IDENTITY_AND_PRIVACY.md`); tenant isolation on FHIR read/search | Met (core); TLS env-gated |
| Access control | JWT Bearer + capability permissions (`FHIRResourcePermission`); SMART scopes declared | Met (app JWT); AfyaLink IdP **to wire** |
| Accountability / audit | Audit events on identity view and FHIR reference resolve; claim/dispense domain audits | Partial — expand ATNA-style FHIR access audit |
| Data subject rights (access / correction) | Patient APIs + internal identity workflows | Partial — formal DSAR procedure ops |
| Retention | Domain retention policies; claim data per Medical Records Act | Ops / policy |
| Breach notification | Ops runbook (DHA 24h / ODPC 72h per IG security guidance) | **Gap** — document in ops |
| Cross-border transfer | Default: keep PHI in Kenya-hosted environments | Ops / contract |
| ODPC registration | Facility Certificate of Data Handler/Processor | **Org legal** — not software |

## FHIR / HIE security expectations (from Kenya eClaims / KPS IG security)

- HTTPS TLS 1.2+ on all FHIR endpoints in production — **SHALL**
- OAuth 2.0 / SMART on FHIR — **SHALL** (discovery live; IdP env-wired)
- Role-based access — **SHALL**
- Immutable audit of access — **SHALL** (strengthen FHIR read/search logging)
- Mutual TLS for system-to-system HIE — **SHOULD** when DHA requires it

## Engineering rules (agents / developers)

1. Never expose full national IDs or CR payloads on POS/public surfaces without
   `patients.identity.view` (or equivalent) + audit reason.
2. HIE Bundles MUST minimise to profile-required elements (no drive-by PHI).
3. Do not log FHIR resource bodies containing PHI at INFO in production.
4. Claims/preauth payloads: purpose = adjudication only; no secondary commercial
   reuse without consent.

Related: `docs/domain/PATIENT_IDENTITY_AND_PRIVACY.md`, `docs/domain/POS_PATIENT_PRIVACY.md`,
`docs/fhir/FHIR_CONFORMANCE.md`.
