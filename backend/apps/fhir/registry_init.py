from apps.fhir.constants import (
    PERMISSION_ALLERGYINTOLERANCE_READ,
    PERMISSION_ALLERGYINTOLERANCE_WRITE,
    PERMISSION_AUDITEVENT_READ,
    PERMISSION_CODESYSTEM_READ,
    PERMISSION_CONDITION_READ,
    PERMISSION_CONDITION_WRITE,
    PERMISSION_DIAGNOSTICREPORT_READ,
    PERMISSION_DIAGNOSTICREPORT_WRITE,
    PERMISSION_DOCUMENTREFERENCE_READ,
    PERMISSION_DOCUMENTREFERENCE_WRITE,
    PERMISSION_ENCOUNTER_READ,
    PERMISSION_ENCOUNTER_WRITE,
    PERMISSION_LOCATION_READ,
    PERMISSION_MEDICATION_READ,
    PERMISSION_MEDICATIONADMINISTRATION_READ,
    PERMISSION_MEDICATIONADMINISTRATION_WRITE,
    PERMISSION_MEDICATIONDISPENSE_READ,
    PERMISSION_MEDICATIONDISPENSE_WRITE,
    PERMISSION_MEDICATIONREQUEST_READ,
    PERMISSION_MEDICATIONREQUEST_WRITE,
    PERMISSION_MEDICATIONSTATEMENT_READ,
    PERMISSION_OBSERVATION_READ,
    PERMISSION_OBSERVATION_WRITE,
    PERMISSION_ORGANIZATION_READ,
    PERMISSION_PATIENT_READ,
    PERMISSION_PATIENT_WRITE,
    PERMISSION_PRACTITIONER_READ,
    PERMISSION_VALUESET_READ,
)
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
from apps.fhir.services.resource_lookup import (
    LocationLookupService,
    OrganizationLookupService,
    PatientLookupService,
    PractitionerLookupService,
    PractitionerRoleLookupService,
)
from apps.fhir.services.resource_registry import FHIRResourceRegistry, ResourceInteraction, ResourceRegistration
from apps.fhir.services.value_set import ValueSetLookupService


def init_registry():
    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="Organization",
            converter_class=OrganizationConverter,
            service_class=OrganizationLookupService,
            interactions=ResourceInteraction(read=True, search=True),
            search_parameters=["_id", "identifier", "name", "active"],
            read_permission=PERMISSION_ORGANIZATION_READ
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="Location",
            converter_class=LocationConverter,
            service_class=LocationLookupService,
            interactions=ResourceInteraction(read=True, search=True),
            search_parameters=["_id", "identifier", "name", "organization", "status"],
            read_permission=PERMISSION_LOCATION_READ
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="Patient",
            converter_class=PatientConverter,
            service_class=PatientLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "identifier", "name", "birthdate", "active"],
            read_permission=PERMISSION_PATIENT_READ,
            write_permission=PERMISSION_PATIENT_WRITE
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="Practitioner",
            converter_class=PractitionerConverter,
            service_class=PractitionerLookupService,
            interactions=ResourceInteraction(read=True, search=True),
            search_parameters=["_id", "identifier", "name", "active"],
            read_permission=PERMISSION_PRACTITIONER_READ
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="PractitionerRole",
            converter_class=PractitionerRoleConverter,
            service_class=PractitionerRoleLookupService,
            interactions=ResourceInteraction(read=True, search=True),
            search_parameters=["_id", "practitioner", "organization", "location"],
            read_permission=PERMISSION_PRACTITIONER_READ
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="Medication",
            converter_class=MedicationConverter,
            service_class=MedicationLookupService,
            interactions=ResourceInteraction(read=True, search=True),
            search_parameters=["_id", "code", "status"],
            read_permission=PERMISSION_MEDICATION_READ
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="MedicationRequest",
            converter_class=MedicationRequestConverter,
            service_class=MedicationRequestLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "identifier", "subject", "requester", "status", "medication"],
            read_permission=PERMISSION_MEDICATIONREQUEST_READ,
            write_permission=PERMISSION_MEDICATIONREQUEST_WRITE
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="MedicationDispense",
            converter_class=MedicationDispenseConverter,
            service_class=MedicationDispenseLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "identifier", "subject", "prescription", "status", "medication"],
            read_permission=PERMISSION_MEDICATIONDISPENSE_READ,
            write_permission=PERMISSION_MEDICATIONDISPENSE_WRITE
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="MedicationStatement",
            converter_class=MedicationStatementConverter,
            service_class=MedicationStatementLookupService,
            interactions=ResourceInteraction(read=True, search=True),
            search_parameters=["_id", "identifier", "subject", "status", "medication"],
            read_permission=PERMISSION_MEDICATIONSTATEMENT_READ
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="AuditEvent",
            converter_class=AuditEventConverter,
            service_class=AuditEventLookupService,
            interactions=ResourceInteraction(read=True, search=True),
            search_parameters=["_id", "agent", "entity", "type"],
            read_permission=PERMISSION_AUDITEVENT_READ
        )
    )

    # --- PHASE 7.1 RESOURCES ---

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="AllergyIntolerance",
            converter_class=AllergyIntoleranceConverter,
            service_class=AllergyIntoleranceLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "patient", "clinical-status", "code", "criticality"],
            read_permission=PERMISSION_ALLERGYINTOLERANCE_READ,
            write_permission=PERMISSION_ALLERGYINTOLERANCE_WRITE,
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="Condition",
            converter_class=ConditionConverter,
            service_class=ConditionLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "patient", "clinical-status", "verification-status", "category", "code", "encounter"],
            read_permission=PERMISSION_CONDITION_READ,
            write_permission=PERMISSION_CONDITION_WRITE,
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="Encounter",
            converter_class=EncounterConverter,
            service_class=EncounterLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "patient", "status", "class", "service-provider", "participant"],
            read_permission=PERMISSION_ENCOUNTER_READ,
            write_permission=PERMISSION_ENCOUNTER_WRITE,
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="MedicationAdministration",
            converter_class=MedicationAdministrationConverter,
            service_class=MedicationAdministrationLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "patient", "status", "medication", "request", "performer", "context"],
            read_permission=PERMISSION_MEDICATIONADMINISTRATION_READ,
            write_permission=PERMISSION_MEDICATIONADMINISTRATION_WRITE,
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="Observation",
            converter_class=ObservationConverter,
            service_class=ObservationLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "patient", "subject", "status", "category", "code", "encounter"],
            read_permission=PERMISSION_OBSERVATION_READ,
            write_permission=PERMISSION_OBSERVATION_WRITE,
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="DiagnosticReport",
            converter_class=DiagnosticReportConverter,
            service_class=DiagnosticReportLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "patient", "status", "category", "code", "result", "encounter"],
            read_permission=PERMISSION_DIAGNOSTICREPORT_READ,
            write_permission=PERMISSION_DIAGNOSTICREPORT_WRITE,
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="DocumentReference",
            converter_class=DocumentReferenceConverter,
            service_class=DocumentReferenceLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=True, update=True),
            search_parameters=["_id", "patient", "status", "type", "category", "author"],
            read_permission=PERMISSION_DOCUMENTREFERENCE_READ,
            write_permission=PERMISSION_DOCUMENTREFERENCE_WRITE,
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="CodeSystem",
            converter_class=CodeSystemConverter,
            service_class=CodeSystemLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=False, update=False),
            search_parameters=["_id", "url", "version", "name", "status"],
            read_permission=PERMISSION_CODESYSTEM_READ
        )
    )

    FHIRResourceRegistry.register(
        ResourceRegistration(
            resource_type="ValueSet",
            converter_class=ValueSetConverter,
            service_class=ValueSetLookupService,
            interactions=ResourceInteraction(read=True, search=True, create=False, update=False),
            search_parameters=["_id", "url", "version", "name", "status"],
            read_permission=PERMISSION_VALUESET_READ
        )
    )
