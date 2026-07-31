"""Kenya eClaims FHIR Implementation Guide — locked for reimbursement flows.

Package: fhir.kenyaClaimsIG @ 0.1.0 (dev-build)
Artifacts: https://build.fhir.org/ig/IntelliSOFT-Consulting/Kenya-eClaims-FHIR-IG/artifacts.html
Install: npm --registry https://fhir.dha.go.ke/npm install fhir.kenyaClaimsIG@0.1.0

Use this IG when exchanging claims, preauthorization, coverage, payment notice,
or dispensing-for-reimbursement payloads. Pure clinical pharmacy exchange
(prescriptions not tied to a claim) uses kenya_ig.py (eRx) + base R4 instead.
"""
from __future__ import annotations

KENYA_CLAIMS_IG_PACKAGE = "fhir.kenyaClaimsIG"
KENYA_CLAIMS_IG_VERSION = "0.1.0"
KENYA_CLAIMS_IG_NAME = "Kenya eClaims FHIR Implementation Guide"
KENYA_CLAIMS_IG_HOME = "https://build.fhir.org/ig/IntelliSOFT-Consulting/Kenya-eClaims-FHIR-IG/"
KENYA_CLAIMS_IG_ARTIFACTS = (
    "https://build.fhir.org/ig/IntelliSOFT-Consulting/Kenya-eClaims-FHIR-IG/artifacts.html"
)
KENYA_CLAIMS_IG_NPM_REGISTRY = "https://fhir.dha.go.ke/npm"
# Canonical base used by published StructureDefinitions (UAT may move to production).
KENYA_CLAIMS_PROFILE_BASE = "https://nshr-uat.sha.go.ke/fhir/StructureDefinition"
# Alternate canonical published on some DHA-hosted pages.
KENYA_CLAIMS_PROFILE_BASE_ALT = "https://fhir.dha.go.ke/eclaims/StructureDefinition"

PROFILES: dict[str, tuple[str, ...]] = {
    "Claim": (
        f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-claimbase",
        f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-claim",
    ),
    "ClaimResponse": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-claimresponse",),
    "Coverage": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-coverage",),
    "Patient": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-patient",),
    "Practitioner": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-practitioner",),
    "Organization": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-organization",),
    "Encounter": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-encounter",),
    "EpisodeOfCare": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-episodeofcare",),
    "Condition": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-condition",),
    "DiagnosticReport": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-diagnosticreport",),
    "MedicationRequest": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-medicationrequest",),
    "MedicationDispense": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-medicationdispense",),
    "MedicationStatement": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-medicationstatement",),
    "PaymentNotice": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-paymentnotice",),
    "Provenance": (f"{KENYA_CLAIMS_PROFILE_BASE}/ke-eclaims-provenance",),
}

# Resource types that MUST carry Claims IG profiles when used for reimbursement.
REIMBURSEMENT_RESOURCE_TYPES = frozenset(PROFILES.keys())


def claims_profiles_for(resource_type: str) -> list[str]:
    return list(PROFILES.get(resource_type, ()))


def validator_ig_arg() -> str:
    """Argument for the official HL7 validator CLI."""
    return f"{KENYA_CLAIMS_IG_PACKAGE}#{KENYA_CLAIMS_IG_VERSION}"
