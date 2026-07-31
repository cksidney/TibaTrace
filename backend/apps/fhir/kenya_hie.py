"""DHA / Kenya HIE exchange conventions (registries, coding, wire formats).

Source of truth for Client Registry (CR), Facility Registry (FR), Health Worker
Registry (HWR), Drug Registry (KEMSA), and wire-level conventions required by
DHA HIE / AfyaLink integrations. Pair with kenya_ig.py (clinical eRx) and
kenya_claims_ig.py (claims / preauth / reimbursement).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# --- Wire conventions (exact) -------------------------------------------------
CONTENT_TYPE_FHIR_JSON = "application/fhir+json"
CURRENCY_CODE = "KES"
DATE_FORMAT = "ISO-8601"  # FHIR date / dateTime / instant
AUTH_SCHEME = "Bearer"  # JWT from AfyaLink developer portal / SMART IdP

SYSTEM_ENCOUNTER_TYPES = "https://shr.kenya-hie.health/encounter-types"

# --- Live DHA registries (resolve; do not invent local-only national IDs) ------
CLIENT_REGISTRY_HOST = "cr.kenya-hie.health"
CLIENT_REGISTRY_BASE = f"https://{CLIENT_REGISTRY_HOST}"
CLIENT_REGISTRY_PATIENT_TEMPLATE = f"{CLIENT_REGISTRY_BASE}/api/v4/Patient/{{cr_id}}"
# Identifier.system used when storing a Client Registry ID on a local Patient.
SYSTEM_CLIENT_REGISTRY_ID = f"{CLIENT_REGISTRY_BASE}/fhir/NamingSystem/cr-id"

# Facility Registry — host confirmed via env in each deployment (DHA FR).
FACILITY_REGISTRY_HOST_DEFAULT = "fr.kenya-hie.health"
SYSTEM_MFL_FACILITY = "https://nshr-uat.sha.go.ke/fhir/NamingSystem/mfl-facility-code"

# Health Worker Registry — practitioner licence numbers.
HEALTH_WORKER_REGISTRY_HOST_DEFAULT = "hwr.kenya-hie.health"
SYSTEM_PRACTITIONER_LICENSE = "https://nshr-uat.sha.go.ke/fhir/NamingSystem/practitioner-license"

# Drug Registry — national catalogue via KEMSA / eTCD / PPB (not a free-form local code).
DRUG_REGISTRY_VIA = "KEMSA / Kenya eTCD / MOH PPB (OCL)"
SYSTEM_PPB_GENERIC = "https://ocl.kenya.go.ke/orgs/MOHPPB/sources/GenericProducts/"

# Hosts that MAY appear in absolute FHIR References for HIE exchange.
DEFAULT_HIE_REFERENCE_HOSTS = (
    CLIENT_REGISTRY_HOST,
    "shr.kenya-hie.health",
    "nshr-uat.sha.go.ke",
    "nshr.sha.go.ke",
    "fhir.dha.go.ke",
    "kps.dha.go.ke",
    FACILITY_REGISTRY_HOST_DEFAULT,
    HEALTH_WORKER_REGISTRY_HOST_DEFAULT,
)

# Local lineage systems (internal only — never sole Coding on HIE payloads).
SYSTEM_LOCAL_PATIENT_REFERENCE = "https://dawatrace.health/fhir/system/patient-reference"


def client_registry_patient_url(cr_id: str) -> str:
    return CLIENT_REGISTRY_PATIENT_TEMPLATE.format(cr_id=str(cr_id).strip())


def extract_client_registry_id(patient: Any) -> str | None:
    """Return CR ID from patient identifiers when present."""
    if patient is None:
        return None
    identifiers = getattr(patient, "identifiers", None)
    if identifiers is None:
        return None
    rows = identifiers.all() if hasattr(identifiers, "all") else identifiers
    for row in rows:
        system = str(getattr(row, "system", "") or "")
        value = str(getattr(row, "value", "") or "").strip()
        if not value:
            continue
        if system in {SYSTEM_CLIENT_REGISTRY_ID, CLIENT_REGISTRY_BASE} or CLIENT_REGISTRY_HOST in system:
            return value
        # Absolute CR Patient URL stored as identifier value.
        if CLIENT_REGISTRY_HOST in value and "/Patient/" in value:
            return value.rstrip("/").rsplit("/", 1)[-1]
    return None


def patient_subject_reference(patient: Any, *, local_id: Any = None) -> str:
    """Prefer absolute CR Patient URL for HIE; fall back to local relative ref."""
    cr_id = extract_client_registry_id(patient)
    if cr_id:
        return client_registry_patient_url(cr_id)
    pid = local_id if local_id is not None else getattr(patient, "id", None)
    return f"Patient/{pid}"


def is_hie_registry_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.lower()
    return host in {h.lower() for h in DEFAULT_HIE_REFERENCE_HOSTS} or host.endswith(".kenya-hie.health")


def money_kes(amount: float | int | str) -> dict[str, Any]:
    """FHIR Money dict with the literal currency string required by DHA."""
    return {"value": float(amount), "currency": CURRENCY_CODE}


def absolute_reference_host(url: str) -> str | None:
    return urlparse(url).hostname
