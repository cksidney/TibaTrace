# Kenya HIE registries & wire conventions

DHA requires live registry resolution for national identifiers and exact
exchange conventions on the HIE / AfyaLink boundary.

Module: `backend/apps/fhir/kenya_hie.py`

## Registries (resolve — do not invent local-only national IDs)

| Registry | Purpose | Canonical / host | Status |
|----------|---------|------------------|--------|
| **Client Registry (CR)** | Patient identity | `https://cr.kenya-hie.health` — Patient URL `…/api/v4/Patient/{CR-ID}` | Constants + subject ref helper; live CR client **not yet wired** |
| **Facility Registry (FR)** | Facility / MFL | `DAWATRACE_FHIR_FACILITY_REGISTRY_BASE` (default `https://fr.kenya-hie.health`); MFL NamingSystem on NSHR | Env stub; map Organization identifiers to MFL |
| **Health Worker Registry (HWR)** | Practitioner licence | `DAWATRACE_FHIR_HEALTH_WORKER_REGISTRY_BASE` | Env stub; emit licence Identifier |
| **Drug Registry** | Products | KEMSA / eTCD / MOH PPB OCL | Catalogue import docs; FHIR Coding secondary PPB + primary RxNorm |

Absolute reference hosts for CR/FR/HWR/NSHR/DHA are allow-listed in
`FHIR_ALLOWED_ABSOLUTE_REFERENCE_HOSTS` (+ `DEFAULT_HIE_REFERENCE_HOSTS`).

### Client Registry on Patient

1. Store CR ID on `PatientIdentifier` with system  
   `https://cr.kenya-hie.health/fhir/NamingSystem/cr-id`.
2. Clinical converters prefer  
   `https://cr.kenya-hie.health/api/v4/Patient/{CR-ID}` as `subject.reference`
   when that identifier is present (`patient_subject_reference`).
3. Local relative `Patient/{uuid}` remains for intra-tenant gateway reads when
   no CR ID is linked.

## Wire conventions (exact)

| Convention | Value |
|------------|--------|
| Content-Type | `application/fhir+json` (`FHIRJSONRenderer` on FHIR views) |
| Currency | Literal string **`KES`** (`money_kes()` / `FHIR_DEFAULT_CURRENCY`) |
| Dates | ISO 8601 (FHIR `date` / `dateTime` / `instant`) |
| Encounter types | `https://shr.kenya-hie.health/encounter-types` on `Encounter.type` |
| Auth | `Bearer` JWT — AfyaLink developer portal / SMART (`DAWATRACE_FHIR_SMART_*`, `DAWATRACE_FHIR_AFYALINK_TOKEN_URL`) |

## Auth note

Application APIs already accept SimpleJWT `Bearer` tokens. HIE production
exchange MUST use AfyaLink / SMART-issued JWTs; wire endpoints per environment
before claiming HIE certification.
