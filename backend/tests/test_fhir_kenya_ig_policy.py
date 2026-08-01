"""Policy tests for locked Kenya ePrescription FHIR IG adoption."""

from fhir.resources.patient import Patient as FHIRPatient

from apps.fhir.kenya_ig import (
    KENYA_ERX_IG_VERSION,
    PROFILES,
    profiles_for,
)
from apps.fhir.registry_init import init_registry
from apps.fhir.services.capability_statement import CapabilityStatementService
from apps.fhir.services.resource_meta import apply_declared_profiles
from apps.fhir.services.resource_registry import (
    FHIRResourceRegistry,
    ResourceInteraction,
    ResourceRegistration,
)


def setup_module():
    FHIRResourceRegistry._registry.clear()
    init_registry()


def test_kenya_erx_ig_version_locked():
    assert KENYA_ERX_IG_VERSION == "0.1.0"


def test_medication_request_declares_kenya_profile():
    assert profiles_for("MedicationRequest") == [
        "https://nshr-uat.sha.go.ke/fhir/StructureDefinition/ke-medication-request",
    ]


def test_patient_has_no_invented_kenya_profile():
    # Kenya eRx 0.1.0 does not publish a Patient profile — do not invent one.
    assert profiles_for("Patient") == []


def test_registry_supported_profiles_populated_for_erx_resources():
    reg = FHIRResourceRegistry.get_registration("MedicationDispense")
    assert reg.supported_profiles
    assert reg.supported_profiles[0].endswith("/ke-medication-dispense")


def test_apply_declared_profiles_sets_meta_profile():
    patient = FHIRPatient(id="p1", gender="unknown")
    # Force-apply MedicationRequest profile list onto a Patient only to exercise helper
    # with an explicit extra list (Patient itself has no Kenya profile).
    apply_declared_profiles(patient, "Patient", extra=["https://example.org/StructureDefinition/test"])
    assert patient.meta is not None
    assert "https://example.org/StructureDefinition/test" in patient.meta.profile


def test_capability_statement_search_param_types_are_not_all_string():
    statement = CapabilityStatementService.generate()
    patient = next(r for r in statement.rest[0].resource if r.type == "Patient")
    by_name = {p.name: p.type for p in patient.searchParam}
    assert by_name["_id"] == "token"
    assert by_name["identifier"] == "token"
    assert by_name["birthdate"] == "date"
    assert by_name["name"] == "string"


def test_capability_statement_advertises_smart_and_kenya_ig():
    statement = CapabilityStatementService.generate()
    assert statement.instantiates
    assert any("igeprescriptions.intellisoftkenya.com" in u for u in statement.instantiates)
    assert any("Kenya-eClaims" in u or "kenyaClaims" in u.lower() for u in statement.instantiates)
    security = statement.rest[0].security
    assert security is not None
    assert security.service[0].coding[0].code == "SMART-on-FHIR"


def test_search_parameter_spec_infers_reference():
    # bare construction defaults type to string; inference happens when coercing from str
    reg = ResourceRegistration(
        resource_type="X",
        converter_class=object,
        service_class=object,
        interactions=ResourceInteraction(read=True),
        search_parameters=["subject", "status", "authoredon"],
    )
    types = {p.name: p.type for p in reg.search_parameter_specs()}
    assert types["subject"] == "reference"
    assert types["status"] == "token"
    assert types["authoredon"] == "date"


def test_profiles_cover_core_erx_set():
    for resource in (
        "MedicationRequest",
        "MedicationDispense",
        "Medication",
        "MedicationAdministration",
        "MedicationStatement",
        "AllergyIntolerance",
        "Encounter",
    ):
        assert resource in PROFILES
        assert profiles_for(resource)
