from django.urls import path

from apps.fhir.views.allergy_intolerance import AllergyIntoleranceView
from apps.fhir.views.audit_event import AuditEventView
from apps.fhir.views.bundle import BundleView
from apps.fhir.views.capability import CapabilityStatementView
from apps.fhir.views.code_system import CodeSystemValidateCodeView, CodeSystemView
from apps.fhir.views.condition import ConditionView
from apps.fhir.views.diagnostic_report import DiagnosticReportView
from apps.fhir.views.document_reference import DocumentReferenceView
from apps.fhir.views.encounter import EncounterView
from apps.fhir.views.location import LocationReadView
from apps.fhir.views.medication import MedicationReadView
from apps.fhir.views.medication_administration import MedicationAdministrationView
from apps.fhir.views.medication_dispense import MedicationDispenseView
from apps.fhir.views.medication_request import MedicationRequestView
from apps.fhir.views.medication_statement import MedicationStatementView
from apps.fhir.views.observation import ObservationView
from apps.fhir.views.organization import OrganizationReadView
from apps.fhir.views.patient import PatientReadView
from apps.fhir.views.practitioner import PractitionerReadView
from apps.fhir.views.practitioner_role import PractitionerRoleReadView
from apps.fhir.views.smart_configuration import SmartConfigurationView
from apps.fhir.views.value_set import ValueSetExpandView, ValueSetValidateCodeView, ValueSetView

app_name = "fhir"

urlpatterns = [
    path('metadata', CapabilityStatementView.as_view(), name='metadata'),
    path('.well-known/smart-configuration', SmartConfigurationView.as_view(), name='smart-configuration'),
    path('Organization/<str:id>', OrganizationReadView.as_view(), name='organization-read'),
    path('Organization', OrganizationReadView.as_view(), name='organization-search'),
    path('Location/<str:id>', LocationReadView.as_view(), name='location-read'),
    path('Location', LocationReadView.as_view(), name='location-search'),
    path('Patient/<str:id>', PatientReadView.as_view(), name='patient-read'),
    path('Patient', PatientReadView.as_view(), name='patient-search'),
    path('Practitioner/<str:id>', PractitionerReadView.as_view(), name='practitioner-read'),
    path('Practitioner', PractitionerReadView.as_view(), name='practitioner-search'),
    path('PractitionerRole/<str:id>', PractitionerRoleReadView.as_view(), name='practitioner-role-read'),
    path('PractitionerRole', PractitionerRoleReadView.as_view(), name='practitioner-role-search'),
    path('Medication/<str:id>', MedicationReadView.as_view(), name='medication-read'),
    path('Medication', MedicationReadView.as_view(), name='medication-search'),
    path('MedicationRequest', MedicationRequestView.as_view(), name='medication-request-collection'),
    path('MedicationRequest/<str:id>', MedicationRequestView.as_view(), name='medication-request-resource'),
    path('MedicationDispense', MedicationDispenseView.as_view(), name='medication-dispense-collection'),
    path('MedicationDispense/<str:id>', MedicationDispenseView.as_view(), name='medication-dispense-resource'),
    path('MedicationStatement', MedicationStatementView.as_view(), name='medication-statement-collection'),
    path('MedicationStatement/<str:id>', MedicationStatementView.as_view(), name='medication-statement-resource'),
    path('AuditEvent', AuditEventView.as_view(), name='audit-event-collection'),
    path('AuditEvent/<str:id>', AuditEventView.as_view(), name='audit-event-resource'),

    path('AllergyIntolerance', AllergyIntoleranceView.as_view(), name='allergy-intolerance-collection'),
    path('AllergyIntolerance/<str:id>', AllergyIntoleranceView.as_view(), name='allergy-intolerance-resource'),
    path('Condition', ConditionView.as_view(), name='condition-collection'),
    path('Condition/<str:id>', ConditionView.as_view(), name='condition-resource'),
    path('Encounter', EncounterView.as_view(), name='encounter-collection'),
    path('Encounter/<str:id>', EncounterView.as_view(), name='encounter-resource'),
    path('MedicationAdministration', MedicationAdministrationView.as_view(), name='medication-administration-collection'),
    path('MedicationAdministration/<str:id>', MedicationAdministrationView.as_view(), name='medication-administration-resource'),
    path('Observation', ObservationView.as_view(), name='observation-collection'),
    path('Observation/<str:id>', ObservationView.as_view(), name='observation-resource'),
    path('DiagnosticReport', DiagnosticReportView.as_view(), name='diagnostic-report-collection'),
    path('DiagnosticReport/<str:id>', DiagnosticReportView.as_view(), name='diagnostic-report-resource'),
    path('DocumentReference', DocumentReferenceView.as_view(), name='document-reference-collection'),
    path('DocumentReference/<str:id>', DocumentReferenceView.as_view(), name='document-reference-resource'),
    path('CodeSystem', CodeSystemView.as_view(), name='code-system-collection'),
    path('CodeSystem/$validate-code', CodeSystemValidateCodeView.as_view(), name='code-system-validate'),
    path('CodeSystem/<str:id>', CodeSystemView.as_view(), name='code-system-resource'),
    path('ValueSet', ValueSetView.as_view(), name='value-set-collection'),
    path('ValueSet/$validate-code', ValueSetValidateCodeView.as_view(), name='value-set-validate'),
    path('ValueSet/$expand', ValueSetExpandView.as_view(), name='value-set-expand'),
    path('ValueSet/<str:id>', ValueSetView.as_view(), name='value-set-resource'),

    # Bundle processing
    path('', BundleView.as_view(), name='bundle-root'),
]
