# Kenya FHIR terminology bindings

Canonical terminology policy for TibaTrace / DawaTrace under the locked
**Kenya ePrescription FHIR IG v0.1.0**.

## Principles (Kenya best practice)

1. Prefer **international** code systems (RxNorm, LOINC, SNOMED CT, ICD-10, ATC)
   on every Coding that leaves the pharmacy boundary.
2. Keep **Kenya PPB / OCL / eTCD / MFL** codes as *additional* Codings (or
   Identifier systems) when a national catalogue code exists — never as the only
   Coding when an international equivalent is known.
3. Never emit display-only strings without `system` + `code`.
4. Local proprietary DawaTrace/Mercato URIs may remain for internal lineage but
   must not be the sole coding on Kenya eRx exchange payloads.

## Required bindings

| Clinical kind | Primary system | Kenya / secondary |
|---------------|----------------|-------------------|
| Medications (product) | RxNorm (`http://www.nlm.nih.gov/research/umls/rxnorm`) | Kenya MOH PPB Generic Products (OCL); ATC when class is needed |
| Medication statements / allergies (substances) | RxNorm or SNOMED CT | PPB Active Components ValueSet |
| Labs / observations | LOINC | — |
| Diagnoses / conditions | ICD-10 or SNOMED CT | — |
| Procedures | SNOMED CT / CPT as appropriate | — |
| Facilities | — | Kenya MFL facility code NamingSystem |
| Prescription identifier | — | Kenya prescription-identifier NamingSystem (per eRx IG) |

## Mapping rule

When importing Kenya eTCD or PPB catalogues:

1. Store the national code on the domain medicine / SKU.
2. Maintain a mapping table to RxNorm (and ATC where available).
3. FHIR Medication / MedicationRequest converters MUST emit RxNorm (or ATC) as a
   Coding and MAY emit the PPB code as a second Coding.

Field-level mapping tables for legacy CSV/HL7v2 imports must be reviewed before
implementation (`docs/fhir/FHIR_CONFORMANCE.md` § mapping policy).
