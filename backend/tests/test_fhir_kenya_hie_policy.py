"""Policy tests for DHA HIE conventions + Kenya Claims IG lock."""

from apps.fhir.api.base import BaseFHIRAPIView
from apps.fhir.kenya_claims_ig import (
    KENYA_CLAIMS_IG_PACKAGE,
    KENYA_CLAIMS_IG_VERSION,
    claims_profiles_for,
    validator_ig_arg,
)
from apps.fhir.kenya_hie import (
    CONTENT_TYPE_FHIR_JSON,
    CURRENCY_CODE,
    SYSTEM_ENCOUNTER_TYPES,
    client_registry_patient_url,
    money_kes,
    patient_subject_reference,
)
from apps.fhir.renderers import FHIRJSONRenderer


def test_claims_ig_package_locked():
    assert KENYA_CLAIMS_IG_PACKAGE == "fhir.kenyaClaimsIG"
    assert KENYA_CLAIMS_IG_VERSION == "0.1.0"
    assert validator_ig_arg() == "fhir.kenyaClaimsIG#0.1.0"


def test_claims_profiles_for_claim_and_medication_dispense():
    assert claims_profiles_for("Claim")
    assert any("ke-eclaims-claimbase" in p for p in claims_profiles_for("Claim"))
    assert claims_profiles_for("MedicationDispense")


def test_wire_conventions():
    assert CONTENT_TYPE_FHIR_JSON == "application/fhir+json"
    assert CURRENCY_CODE == "KES"
    assert SYSTEM_ENCOUNTER_TYPES == "https://shr.kenya-hie.health/encounter-types"
    assert money_kes(10) == {"value": 10.0, "currency": "KES"}


def test_client_registry_patient_url():
    assert (
        client_registry_patient_url("CR-123")
        == "https://cr.kenya-hie.health/api/v4/Patient/CR-123"
    )


def test_patient_subject_reference_prefers_cr():
    class _Id:
        def __init__(self, system, value):
            self.system = system
            self.value = value

    class _Patient:
        id = "local-1"
        identifiers = [
            _Id("https://cr.kenya-hie.health/fhir/NamingSystem/cr-id", "ABC"),
        ]

    assert patient_subject_reference(_Patient()) == (
        "https://cr.kenya-hie.health/api/v4/Patient/ABC"
    )
    assert patient_subject_reference(None, local_id="x") == "Patient/x"


def test_fhir_views_use_fhir_json_renderer():
    assert FHIRJSONRenderer in BaseFHIRAPIView.renderer_classes
    assert FHIRJSONRenderer.media_type == "application/fhir+json"
