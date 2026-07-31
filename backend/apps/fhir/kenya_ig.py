"""Kenya ePrescription FHIR Implementation Guide — locked target.

Canonical profiles use the SHA NSHR StructureDefinition base published with the
Kenya ePrescription IG v0.1.0 (Digital Health Agency / SHA). The UAT host may
move when production NSHR URLs are published; keep this module as the single
source of truth and update together with docs/fhir/FHIR_CONFORMANCE.md.
"""
from __future__ import annotations

KENYA_ERX_IG_NAME = "Kenya ePrescription FHIR Implementation Guide"
KENYA_ERX_IG_VERSION = "0.1.0"
KENYA_ERX_IG_HOME = "https://igeprescriptions.intellisoftkenya.com/"
# Official StructureDefinition base used by the published IG artifacts.
KENYA_ERX_PROFILE_BASE = "https://nshr-uat.sha.go.ke/fhir/StructureDefinition"

# International terminology systems (canonical).
SYSTEM_RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SYSTEM_LOINC = "http://loinc.org"
SYSTEM_SNOMED = "http://snomed.info/sct"
SYSTEM_ICD10 = "http://hl7.org/fhir/sid/icd-10"
SYSTEM_ATC = "http://www.whocc.no/atc"

# Kenya-local systems used alongside international codes (secondary mapping).
# Prefer kenya_hie.py for live registry hosts (CR / FR / HWR / Drug).
SYSTEM_KE_PPB_GENERIC = "https://ocl.kenya.go.ke/orgs/MOHPPB/sources/GenericProducts/"
SYSTEM_KE_MFL = "https://nshr-uat.sha.go.ke/fhir/NamingSystem/mfl-facility-code"

# Clinical (non-claim) exchange: Kenya eRx IG + base R4 + DHA code systems.
# Claims / preauth / dispensing-for-reimbursement: see kenya_claims_ig.py.

PROFILES: dict[str, tuple[str, ...]] = {
    # Kenya eRx IG profiles (resource types declared in the IG artifacts).
    "MedicationRequest": (f"{KENYA_ERX_PROFILE_BASE}/ke-medication-request",),
    "MedicationDispense": (f"{KENYA_ERX_PROFILE_BASE}/ke-medication-dispense",),
    "Medication": (f"{KENYA_ERX_PROFILE_BASE}/ke-medication",),
    "MedicationAdministration": (f"{KENYA_ERX_PROFILE_BASE}/ke-medication-administration",),
    "MedicationStatement": (f"{KENYA_ERX_PROFILE_BASE}/ke-medication-statement",),
    "AllergyIntolerance": (f"{KENYA_ERX_PROFILE_BASE}/ke-allergy-intolerance",),
    "Encounter": (f"{KENYA_ERX_PROFILE_BASE}/ke-encounter",),
    # Patient / Practitioner / Organization: not profiled in Kenya eRx 0.1.0 —
    # expose base R4 (no invented profile URL).
}

# SMART scopes we intend to support for Kenya pharmacy / HIE exchange.
SMART_SCOPES_DECLARED = (
    "openid",
    "fhirUser",
    "launch",
    "launch/patient",
    "patient/*.read",
    "patient/MedicationRequest.read",
    "patient/MedicationDispense.read",
    "patient/MedicationStatement.read",
    "patient/AllergyIntolerance.read",
    "user/*.read",
    "user/MedicationRequest.write",
    "user/MedicationDispense.write",
    "system/*.read",
)


def profiles_for(resource_type: str) -> list[str]:
    return list(PROFILES.get(resource_type, ()))
