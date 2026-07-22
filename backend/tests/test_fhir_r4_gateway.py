from __future__ import annotations

import fhir.resources
import pydantic
import pytest
from fhir.resources.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.patient import Patient as FHIRPatient
from rest_framework.test import APIClient

from apps.clinical.models import (
    ClinicalCondition,
    ClinicalDiagnosticReport,
    ClinicalDocument,
    ClinicalEncounter,
    ClinicalObservation,
    MedicationAdministrationRecord,
)
from apps.fhir.api.bundle_processor import BundleProcessor
from apps.fhir.converters import (
    AllergyIntoleranceConverter,
    AuditEventConverter,
    CodeSystemConverter,
    ConditionConverter,
    DiagnosticReportConverter,
    DocumentReferenceConverter,
    EncounterConverter,
    LocationConverter,
    MedicationAdministrationConverter,
    MedicationConverter,
    MedicationDispenseConverter,
    MedicationRequestConverter,
    MedicationStatementConverter,
    ObservationConverter,
    OrganizationConverter,
    PatientConverter,
    PractitionerConverter,
    PractitionerRoleConverter,
    ValueSetConverter,
)
from apps.fhir.exceptions import FHIRReferenceResolutionError
from apps.fhir.registry_init import init_registry
from apps.fhir.services.allergy_intolerance import AllergyIntoleranceLookupService
from apps.fhir.services.audit_event import AuditEventLookupService
from apps.fhir.services.code_system import CodeSystemLookupService
from apps.fhir.services.condition import ConditionLookupService
from apps.fhir.services.diagnostic_report import DiagnosticReportLookupService
from apps.fhir.services.document_reference import DocumentReferenceLookupService
from apps.fhir.services.encounter import EncounterLookupService
from apps.fhir.services.medication import MedicationLookupService
from apps.fhir.services.medication_administration import MedicationAdministrationLookupService
from apps.fhir.services.medication_dispense import MedicationDispenseLookupService
from apps.fhir.services.medication_request import MedicationRequestLookupService
from apps.fhir.services.medication_statement import MedicationStatementLookupService
from apps.fhir.services.observation import ObservationLookupService
from apps.fhir.services.reference_resolver import FHIRReferenceResolver
from apps.fhir.services.resource_lookup import (
    LocationLookupService,
    OrganizationLookupService,
    PatientLookupService,
    PractitionerLookupService,
    PractitionerRoleLookupService,
)
from apps.fhir.services.resource_registry import FHIRResourceRegistry
from apps.fhir.services.value_set import ValueSetLookupService
from apps.patients.models import PatientAllergy, PatientIdentifier, PatientMedication
from apps.practitioners.models import PractitionerRole
from apps.prescription.models import (
    Prescription,
    PrescriptionAudit,
    PrescriptionDispense,
    PrescriptionFill,
    PrescriptionItem,
)
from apps.terminology.models import FHIRCodeSystemRegistration, FHIRTerminologyVersion, FHIRValueSetRegistration

pytestmark = [pytest.mark.django_db, pytest.mark.fhir]


RESOURCE_TYPES = (
    "Organization", "Location", "Practitioner", "PractitionerRole", "Patient", "Medication",
    "MedicationRequest", "MedicationDispense", "MedicationStatement", "AllergyIntolerance", "Condition",
    "Encounter", "MedicationAdministration", "Observation", "DiagnosticReport", "DocumentReference",
    "CodeSystem", "ValueSet", "AuditEvent",
)

CONVERTERS = {
    "Organization": OrganizationConverter,
    "Location": LocationConverter,
    "Practitioner": PractitionerConverter,
    "PractitionerRole": PractitionerRoleConverter,
    "Patient": PatientConverter,
    "Medication": MedicationConverter,
    "MedicationRequest": MedicationRequestConverter,
    "MedicationDispense": MedicationDispenseConverter,
    "MedicationStatement": MedicationStatementConverter,
    "AllergyIntolerance": AllergyIntoleranceConverter,
    "Condition": ConditionConverter,
    "Encounter": EncounterConverter,
    "MedicationAdministration": MedicationAdministrationConverter,
    "Observation": ObservationConverter,
    "DiagnosticReport": DiagnosticReportConverter,
    "DocumentReference": DocumentReferenceConverter,
    "CodeSystem": CodeSystemConverter,
    "ValueSet": ValueSetConverter,
    "AuditEvent": AuditEventConverter,
}

SERVICES = {
    "Organization": OrganizationLookupService,
    "Location": LocationLookupService,
    "Practitioner": PractitionerLookupService,
    "PractitionerRole": PractitionerRoleLookupService,
    "Patient": PatientLookupService,
    "Medication": MedicationLookupService,
    "MedicationRequest": MedicationRequestLookupService,
    "MedicationDispense": MedicationDispenseLookupService,
    "MedicationStatement": MedicationStatementLookupService,
    "AllergyIntolerance": AllergyIntoleranceLookupService,
    "Condition": ConditionLookupService,
    "Encounter": EncounterLookupService,
    "MedicationAdministration": MedicationAdministrationLookupService,
    "Observation": ObservationLookupService,
    "DiagnosticReport": DiagnosticReportLookupService,
    "DocumentReference": DocumentReferenceLookupService,
    "CodeSystem": CodeSystemLookupService,
    "ValueSet": ValueSetLookupService,
    "AuditEvent": AuditEventLookupService,
}


@pytest.fixture
def fhir_records(clinical_setup, clinical_user):
    setup = clinical_setup
    tenant = setup["tenant"]
    role = PractitionerRole.all_objects.get(practitioner=setup["practitioner"])
    prescription = Prescription.all_objects.create(
        tenant=tenant,
        patient=setup["patient"],
        practitioner=setup["practitioner"],
        organization=setup["organization"],
        location=setup["location"],
        prescription_number="FHIR-RX-1",
        issued_at=setup["now"],
    )
    item = PrescriptionItem.all_objects.create(
        tenant=tenant,
        prescription=prescription,
        canonical_medicine=setup["medicine_a"],
        medication_name="Demo medicine A",
        dosage_instruction="One daily",
        quantity="10",
    )
    dispense = PrescriptionDispense.all_objects.create(
        tenant=tenant,
        prescription=prescription,
        location=setup["location"],
        dispensed_by=clinical_user,
        idempotency_key="FHIR-DISPENSE-1",
    )
    fill = PrescriptionFill.all_objects.create(
        tenant=tenant, dispense=dispense, item=item, quantity_dispensed="2"
    )
    statement = PatientMedication.all_objects.create(
        tenant=tenant,
        patient=setup["patient"],
        medicine=setup["medicine_a"],
        medication_name="Demo medicine A",
        directions="One daily",
        status="ACTIVE",
    )
    allergy = PatientAllergy.all_objects.create(
        tenant=tenant,
        patient=setup["patient"],
        allergen_name="Penicillin",
        allergen_code="PEN",
        reaction="Rash",
        severity="WARNING",
    )
    encounter = ClinicalEncounter.all_objects.create(
        tenant=tenant,
        patient=setup["patient"],
        status="IN_PROGRESS",
        encounter_class="AMB",
        organization=setup["organization"],
        location=setup["location"],
        practitioner=setup["practitioner"],
        start_time=setup["now"],
    )
    condition = ClinicalCondition.all_objects.create(
        tenant=tenant,
        patient=setup["patient"],
        encounter=encounter,
        clinical_status="ACTIVE",
        verification_status="CONFIRMED",
        code="DEMO-CONDITION",
        display="Demonstration condition",
    )
    observation = ClinicalObservation.all_objects.create(
        tenant=tenant,
        patient=setup["patient"],
        encounter=encounter,
        status="FINAL",
        code="8310-5",
        system="http://loinc.org",
        display="Body temperature",
        effective_time=setup["now"],
        value_quantity="37.1",
        value_unit="Cel",
    )
    report = ClinicalDiagnosticReport.all_objects.create(
        tenant=tenant,
        patient=setup["patient"],
        encounter=encounter,
        status="FINAL",
        code="DEMO-REPORT",
        effective_time=setup["now"],
        conclusion="No critical finding",
    )
    report.observations.add(observation)
    administration = MedicationAdministrationRecord.all_objects.create(
        tenant=tenant,
        patient=setup["patient"],
        encounter=encounter,
        prescription_item=item,
        status="COMPLETED",
        medication_name="Demo medicine A",
        effective_time=setup["now"],
        dosage_text="One tablet",
        performer=setup["practitioner"],
    )
    document = ClinicalDocument.all_objects.create(
        tenant=tenant,
        patient=setup["patient"],
        encounter=encounter,
        status="CURRENT",
        doc_type="NOTE",
        object_url="https://documents.example.test/demo.pdf",
        content_type="application/pdf",
        size_bytes=128,
        hash_sha256="b" * 64,
        author=setup["practitioner"],
    )
    terminology = FHIRTerminologyVersion.all_objects.create(
        tenant=tenant,
        canonical_url="https://dawatrace.health/fhir/terminology/demo",
        version="1",
        publisher="Esenai Group Ltd",
        status="ACTIVE",
        source_name="DawaTrace demonstration terminology",
        source_version="1",
        licence="Internal demonstration only",
    )
    code_system = FHIRCodeSystemRegistration.all_objects.create(
        tenant=tenant,
        version=terminology,
        url="https://dawatrace.health/fhir/CodeSystem/demo",
        name="DawaTraceDemoCodes",
        concepts_json=[{"code": "A", "display": "Alpha"}],
    )
    value_set = FHIRValueSetRegistration.all_objects.create(
        tenant=tenant,
        version=terminology,
        url="https://dawatrace.health/fhir/ValueSet/demo",
        name="DawaTraceDemoValueSet",
        compose_json={"include": [{"system": code_system.url}]},
    )
    audit = PrescriptionAudit.all_objects.create(
        tenant=tenant,
        prescription=prescription,
        event_type="READ",
        user=clinical_user,
    )
    return {
        "Organization": setup["organization"],
        "Location": setup["location"],
        "Practitioner": setup["practitioner"],
        "PractitionerRole": role,
        "Patient": setup["patient"],
        "Medication": setup["medicine_a"],
        "MedicationRequest": item,
        "MedicationDispense": fill,
        "MedicationStatement": statement,
        "AllergyIntolerance": allergy,
        "Condition": condition,
        "Encounter": encounter,
        "MedicationAdministration": administration,
        "Observation": observation,
        "DiagnosticReport": report,
        "DocumentReference": document,
        "CodeSystem": code_system,
        "ValueSet": value_set,
        "AuditEvent": audit,
    }


def test_runtime_is_exact_fhir_r4_stack():
    assert fhir.resources.__version__ == "6.5.0"
    assert pydantic.VERSION == "1.10.26"


def test_registry_exposes_exact_19_resource_types():
    init_registry()
    assert {registration.resource_type for registration in FHIRResourceRegistry.all_registrations()} == set(RESOURCE_TYPES)


@pytest.mark.parametrize("resource_type", RESOURCE_TYPES, ids=RESOURCE_TYPES)
def test_all_19_resources_render_and_reparse_as_r4(resource_type, fhir_records, clinical_setup):
    rendered = CONVERTERS[resource_type]().to_fhir(
        fhir_records[resource_type], {"tenant_id": str(clinical_setup["tenant"].id)}
    )
    assert rendered.errors == []
    assert rendered.fhir_resource.resource_type == resource_type
    reparsed = rendered.fhir_resource.__class__.parse_obj(rendered.fhir_resource.dict(exclude_none=True))
    assert str(reparsed.id) == str(fhir_records[resource_type].id)


@pytest.mark.parametrize("resource_type", RESOURCE_TYPES, ids=RESOURCE_TYPES)
def test_all_19_resource_reads_are_tenant_isolated(resource_type, fhir_records, clinical_setup, tenant_b):
    service = SERVICES[resource_type]
    resource_id = str(fhir_records[resource_type].id)
    assert service.get_by_id(resource_id, str(clinical_setup["tenant"].id)) is not None
    assert service.get_by_id(resource_id, str(tenant_b.id)) is None


@pytest.mark.parametrize("resource_type", RESOURCE_TYPES, ids=RESOURCE_TYPES)
def test_all_19_resource_searches_are_tenant_isolated(resource_type, fhir_records, clinical_setup, tenant_b):
    service = SERVICES[resource_type]
    resource_id = str(fhir_records[resource_type].id)
    assert [str(row.id) for row in service.search({"_id": resource_id, "_count": "5"}, str(clinical_setup["tenant"].id))] == [resource_id]
    assert service.search({"_id": resource_id, "_count": "5"}, str(tenant_b.id)) == []


def test_reference_resolver_is_tenant_qualified(fhir_records, clinical_setup, tenant_b):
    patient = fhir_records["Patient"]
    resolved = FHIRReferenceResolver.resolve(
        f"Patient/{patient.id}", "Patient", str(clinical_setup["tenant"].id)
    )
    assert resolved.id == patient.id
    with pytest.raises(FHIRReferenceResolutionError):
        FHIRReferenceResolver.resolve(f"Patient/{patient.id}", "Patient", str(tenant_b.id))


def test_identifier_reference_resolves_within_tenant(fhir_records, clinical_setup):
    patient = fhir_records["Patient"]
    PatientIdentifier.all_objects.create(
        tenant=clinical_setup["tenant"], patient=patient, system="urn:test:mrn", value="MRN-001"
    )
    resolved = FHIRReferenceResolver.resolve(
        {"identifier": {"system": "urn:test:mrn", "value": "MRN-001"}},
        "Patient",
        str(clinical_setup["tenant"].id),
    )
    assert resolved.id == patient.id


def test_transaction_bundle_creates_patient(clinical_setup, clinical_user):
    patient = FHIRPatient(
        id="4c0ccf8a-6ff8-4f7c-97ff-5b2e6435f908",
        identifier=[Identifier(system="https://dawatrace.health/fhir/system/patient-reference", value="BUNDLE-PAT")],
        name=[HumanName(family="Bundle", given=["Patient"])],
        active=True,
    )
    bundle = Bundle(
        type="transaction",
        entry=[
            BundleEntry(
                fullUrl=f"urn:uuid:{patient.id}",
                resource=patient,
                request=BundleEntryRequest(method="POST", url="Patient"),
            )
        ],
    )
    response = BundleProcessor.process(bundle, str(clinical_setup["tenant"].id), clinical_user)
    assert response.type == "transaction-response"
    assert response.entry[0].response.status == "201 Created"
    assert PatientLookupService.get_by_id(patient.id, str(clinical_setup["tenant"].id)) is not None


def test_batch_bundle_isolates_entry_failures(clinical_setup, clinical_user):
    good = FHIRPatient(
        identifier=[Identifier(system="https://dawatrace.health/fhir/system/patient-reference", value="BATCH-GOOD")],
        active=True,
    )
    bundle = Bundle(
        type="batch",
        entry=[
            BundleEntry(resource=good, request=BundleEntryRequest(method="POST", url="Patient")),
            BundleEntry(resource=good.copy(deep=True), request=BundleEntryRequest(method="DELETE", url="Patient/1")),
        ],
    )
    response = BundleProcessor.process(bundle, str(clinical_setup["tenant"].id), clinical_user)
    assert response.type == "batch-response"
    assert response.entry[0].response.status.startswith("201")
    assert response.entry[1].response.status.startswith("405")


def test_patient_fhir_write_is_idempotent(clinical_setup, clinical_user):
    client = APIClient()
    client.force_authenticate(clinical_user)
    payload = {
        "resourceType": "Patient",
        "identifier": [
            {"system": "https://dawatrace.health/fhir/system/patient-reference", "value": "FHIR-IDEMPOTENT"}
        ],
        "active": True,
        "name": [{"family": "FHIR", "given": ["Idempotent"]}],
    }
    headers = {
        "HTTP_X_TENANT_ID": str(clinical_setup["tenant"].id),
        "HTTP_IDEMPOTENCY_KEY": "FHIR-PATIENT-1",
    }
    first = client.post("/api/fhir/r4/Patient", payload, format="json", **headers)
    second = client.post("/api/fhir/r4/Patient", payload, format="json", **headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert second["X-Idempotent-Replay"] == "true"
    assert first.data["id"] == second.data["id"]


def test_missing_fhir_resource_returns_operation_outcome(clinical_setup, clinical_user):
    client = APIClient()
    client.force_authenticate(clinical_user)
    response = client.get(
        "/api/fhir/r4/Patient/00000000-0000-0000-0000-000000000001",
        HTTP_X_TENANT_ID=str(clinical_setup["tenant"].id),
    )
    assert response.status_code == 404
    assert response.data["resourceType"] == "OperationOutcome"


def test_fhir_search_rejects_unknown_parameter(clinical_setup, clinical_user):
    client = APIClient()
    client.force_authenticate(clinical_user)
    response = client.get(
        "/api/fhir/r4/Patient?unsafe=value",
        HTTP_X_TENANT_ID=str(clinical_setup["tenant"].id),
    )
    assert response.status_code == 400
    assert response.data["resourceType"] == "OperationOutcome"
