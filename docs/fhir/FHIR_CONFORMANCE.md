# TibaTrace / DawaTrace — FHIR Conformance Register

Living register for HL7 FHIR compliance. Update whenever the FHIR gateway,
profiles, terminology, SMART posture, or HIE conventions change.

**Last reviewed:** 2026-07-31  
**Adoption:** Kenya eRx IG + Kenya eClaims IG (dual target) + DHA HIE conventions
+ Data Protection Act 2019 control map.

---

## 1. Technical conformance target

| Lane | Target | When |
|------|--------|------|
| **Base** | FHIR **R4 `4.0.1`** | All HIE / claims / outpatient exchange (DHA-confirmed) |
| **Clinical pharmacy** (Rx not claim-tied) | Base R4 + **Kenya ePrescription IG 0.1.0** + DHA code systems | Encounters, prescriptions, allergies, etc. |
| **Claims / preauth / dispensing-for-reimbursement** | **`fhir.kenyaClaimsIG#0.1.0`** | Pull [artifacts.html](https://build.fhir.org/ig/IntelliSOFT-Consulting/Kenya-eClaims-FHIR-IG/artifacts.html); validate with official validator **against those profiles**, not base R4 alone |

| Item | Value | Module |
|------|--------|--------|
| Runtime | `fhir.resources==6.5.0` | Locked |
| Clinical IG | Kenya eRx `0.1.0` | `kenya_ig.py` |
| Claims IG | `fhir.kenyaClaimsIG` `0.1.0` | `kenya_claims_ig.py` |
| HIE conventions | CR/FR/HWR/Drug, KES, fhir+json, … | `kenya_hie.py` |

### Decision table (adopted)

| Requirement | Decision | Priority | Kenya practice |
|-------------|----------|----------|----------------|
| Implementation Guide | Dual lock | Critical | eRx clinical; Claims IG for reimbursement |
| `meta.profile` | Implement | Critical | eRx profiles on clinical gateway resources |
| SMART / OAuth / AfyaLink JWT | Implement | Critical | Discovery + CapStmt; Bearer JWT from AfyaLink/SMART |
| RxNorm / LOINC / SNOMED | Canonical terminology | High | International primary; PPB/eTCD secondary |
| Official FHIR validator in CI | Mandatory | High | R4 samples; Claims IG script when claim samples exist |
| CapStmt searchParam types | Correct types | Medium | `token` / `reference` / `date` / `string` |
| Live DHA registries | Resolve | Critical | CR / FR / HWR / Drug — see `KENYA_HIE_REGISTRIES.md` |
| Data Protection Act 2019 | Comply | Critical | `KENYA_DATA_PROTECTION_ACT_2019.md` |

---

## 2. Registries

See `docs/fhir/KENYA_HIE_REGISTRIES.md`.

| Registry | Host / integration | Gateway status |
|----------|--------------------|----------------|
| Client Registry | `cr.kenya-hie.health` | Subject URL helper + identifier system; **live API client pending** |
| Facility Registry | env `DAWATRACE_FHIR_FACILITY_REGISTRY_BASE` | Allow-listed; MFL NamingSystem declared |
| Health Worker Registry | env HWR base | Allow-listed; licence NamingSystem declared |
| Drug Registry | KEMSA / eTCD / PPB | Catalogue path; Coding policy in terminology doc |

---

## 3. Coding / wire conventions

| Convention | Exact value | Enforcement |
|------------|-------------|-------------|
| Encounter types | `https://shr.kenya-hie.health/encounter-types` | `Encounter.type` coding |
| Patient references (HIE) | `https://cr.kenya-hie.health/api/v4/Patient/{CR-ID}` | When CR ID linked |
| Currency | `KES` | `money_kes()` / settings |
| Dates | ISO 8601 | FHIR dateTime fields |
| Content-Type | `application/fhir+json` | `FHIRJSONRenderer` |
| Auth | Bearer JWT (AfyaLink / SMART) | App JWT today; IdP env for HIE |

---

## Supported resources (CapabilityStatement)

Exactly **19** resource types on `/api/fhir/r4/` (clinical gateway). Kenya eRx
profiles declared for MedicationRequest, MedicationDispense, Medication,
MedicationAdministration, MedicationStatement, AllergyIntolerance, Encounter.

Patient / Practitioner / Organization remain **base R4** on the clinical
gateway. **Claims IG** publishes eClaims Patient/Practitioner/Organization —
use those profiles only on claim/preauth Bundles (not invented on clinical lane).

FHIR `Claim` / `ClaimResponse` / `Coverage` / `PaymentNotice` are **not yet** on
the 19-resource gateway; insurance today uses proprietary `/api/insurance/`.
Claims IG lock + validator script are in place so converters can land against
the correct profiles.

### Interactions / search / errors

Read/search tenant-scoped; writes gated by `FHIR_WRITE_INTERACTIONS_ENABLED`;
typed `SearchParameterSpec`; `OperationOutcome` on failures.

---

## Terminology

See `docs/fhir/KENYA_TERMINOLOGY_BINDINGS.md`.

---

## Security, privacy & access

| Requirement | Status |
|-------------|--------|
| SMART discovery | `/api/fhir/r4/.well-known/smart-configuration` |
| CapStmt SMART-on-FHIR | Declared |
| AfyaLink / OAuth endpoints | `DAWATRACE_FHIR_SMART_*`, `DAWATRACE_FHIR_AFYALINK_TOKEN_URL` |
| `application/fhir+json` | Enforced on FHIR views |
| Data Protection Act 2019 | Control map in `KENYA_DATA_PROTECTION_ACT_2019.md` |
| TLS / PHI without auth | Production TLS required; PHI APIs authenticated |

---

## Validation

| Layer | Status |
|-------|--------|
| Structural (`fhir.resources`) | Met |
| Official HL7 validator (R4 samples) | `scripts/validate-fhir-samples.sh` |
| Kenya Claims IG profiles | `scripts/validate-fhir-claims-ig.sh` (`-ig fhir.kenyaClaimsIG#0.1.0`) |
| Full Kenya eRx profile package in CI | Not yet mandatory |

Do not claim DHA / SHA certification until profile-level CI is green and live
registries + AfyaLink are wired per environment.

---

## Mapping policy

Field mappings for review: `docs/fhir/KENYA_ERX_FIELD_MAPPINGS.md`.  
Wait for review before large converter rewrites.

---

## Known gaps

1. Live CR/FR/HWR HTTP clients (resolve/validate against registries).
2. FHIR Claim resource converters + Claims IG samples in CI.
3. AfyaLink production IdP endpoints.
4. Full RxNorm/PPB emission on all live converters.
5. NSHR / Claims canonical host promotion (UAT → production) with SHA/DHA.
6. Ops breach-notification runbook; formal DSAR process.

---

## Related

- `docs/fhir/DAWATRACE_FHIR_BASELINE.md`
- `docs/fhir/KENYA_TERMINOLOGY_BINDINGS.md`
- `docs/fhir/KENYA_HIE_REGISTRIES.md`
- `docs/fhir/KENYA_DATA_PROTECTION_ACT_2019.md`
- `docs/fhir/KENYA_ERX_FIELD_MAPPINGS.md`
- `.cursor/rules/fhir-compliance.mdc`
- `backend/apps/fhir/kenya_ig.py`, `kenya_claims_ig.py`, `kenya_hie.py`
