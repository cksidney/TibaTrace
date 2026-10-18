# Kenya National Health Terminology Service Compliance Documentation

**Status:** Current integration/conformance gap assessment; no KNHTS connection or certification asserted  
**Assessment date:** 17 October 2026

## 1. Authority and current reference

The Digital Health Agency's Kenya National Health Terminology Service (KNHTS) is the intended national source for standardized health terms and coded data. At the time checked, the KNHTS knowledge base describes version 1.0 as its first published downloadable data-dictionary iteration and says the dictionary remains under review by the Terminology Service Committee and Chief Terminologist. Therefore implementation must capture the exact version, publication status, licence, update date and approved domain before using a code in a regulated exchange.

References: [KNHTS portal](https://nhts.dha.go.ke/), [KNHTS knowledge base](https://nhts.dha.go.ke/knowledgebase/), [Digital Health Act](https://new.kenyalaw.org/akn/ke/act/2023/15/eng@2023-11-24/source), and [DHA certification regulatory guide](https://certification.dha.go.ke/regulatory-guide).

## 2. TibaTrace implementation observed

The repository contains an internal terminology domain and FHIR R4 CodeSystem/ValueSet endpoints. Existing Kenya terminology guidance documents intended bindings for medicines, allergies, laboratory observations, diagnoses, procedures, facilities and prescription identifiers. The mapping document currently emphasizes RxNorm/LOINC/SNOMED CT/ICD-10 plus Kenya PPB/MFL identifiers where available.

This is a terminology architecture, not proof of direct KNHTS import, current code coverage, approval, licence compliance, update synchronization or DHA certification. The repository review found no evidence sufficient to confirm an authenticated live KNHTS adapter or that each deployed coding binding has been tested against the latest KNHTS dictionary.

## 3. Required conformance controls

1. Maintain a versioned source registry with canonical URI, publisher, release/version, status, effective date, licence, checksum, import time and reviewer.
2. Ingest only an official KNHTS release or approved endpoint; preserve the source artifact and checksum.
3. Map each TibaTrace concept to the correct KNHTS code, display, hierarchy and status. Preserve source code and mapping provenance; never replace an unknown with a guessed equivalent.
4. Distinguish `active`, `retired`, `draft`, `deprecated`, `unmapped` and `locally curated` concepts. Block retired/unmapped codes from outbound regulated payloads unless the profile expressly allows them.
5. Use version-pinned ValueSets for validation and record which version validated each clinical/reporting payload.
6. Apply source terminology licence and redistribution rules. Do not publish copyrighted SNOMED CT or other restricted data without appropriate rights.
7. Provide a governed local synonym/search layer while preserving canonical codes in storage and exchange.
8. Test FHIR CodeSystem/ValueSet responses, unknown-code rejection, version upgrades, inactive codes, historical data, and concurrent tenant access.
9. Define update approval and rollback. A new terminology release must not silently change historical meanings or clinical decisions.

## 4. Gap and action register

| Gap | Required evidence | Owner |
|---|---|---|
| KNHTS source profile/contract not recorded | Written DHA source/API/file guidance and data licence | Integration owner |
| Latest code-set import/version not evidenced | Release identifier, checksum, import report and clinical terminology approval | Terminology lead |
| Code coverage and mapping not reconciled | Mapping matrix for diagnosis, medicine, lab, procedure, facility and reporting domains | Clinical informatics lead |
| No conformance certification found | DHA assessment result/certificate and tested deployed release | Product/compliance owner |
| Change governance not operationally evidenced | Version upgrade, rollback, deprecation and impact-review record | Product owner |

Until closure, user-facing screens must identify the code source/version where it matters, keep unverified local entries distinct, and avoid claiming KNHTS-compliant data exchange.

## 5. Acceptance evidence

The compliance package should contain the official KNHTS release artifact or API contract; provenance/checksum; licence review; TibaTrace concept crosswalk; FHIR/API test results; sample coded resources; approval minutes; deployment digest; and formal DHA decision where required. Re-assess against the latest guidance before each certification submission.
