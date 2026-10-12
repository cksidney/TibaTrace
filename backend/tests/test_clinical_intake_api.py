import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.clinical.models import ClinicalCondition, ClinicalEncounter, ClinicalObservation
from apps.patients.models import Patient
from apps.workflows.models import DomainEvent

pytestmark = pytest.mark.django_db


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_TENANT_ID"] = str(user.tenant_id)
    return client


def test_encounter_intake_uses_domain_rules_and_emits_audit_and_event(clinical_setup, clinical_user):
    response = authenticated_client(clinical_user).post(
        "/api/clinical/encounters/",
        {
            "patient_id": str(clinical_setup["patient"].pk),
            "status": "IN_PROGRESS",
            "encounter_class": "AMB",
            "start_time": timezone.now().isoformat(),
            "reason_code": "FOLLOW_UP",
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    encounter = ClinicalEncounter.all_objects.get(pk=response.json()["id"])
    assert encounter.tenant_id == clinical_setup["tenant"].pk
    assert encounter.patient_id == clinical_setup["patient"].pk
    assert AuditEvent.all_objects.filter(
        tenant=clinical_setup["tenant"],
        action="CLINICAL_RECORD_INGESTED",
        object_id=str(encounter.pk),
    ).exists()
    assert DomainEvent.all_objects.filter(
        tenant=clinical_setup["tenant"],
        aggregate_id=encounter.pk,
        event_type="clinical.encounter.created",
    ).exists()


def test_condition_and_observation_intake_persist_supported_values(clinical_setup, clinical_user):
    client = authenticated_client(clinical_user)
    condition_response = client.post(
        "/api/clinical/conditions/",
        {
            "patient_id": str(clinical_setup["patient"].pk),
            "clinical_status": "ACTIVE",
            "verification_status": "CONFIRMED",
            "code": "J45.9",
            "system": "http://hl7.org/fhir/sid/icd-10",
            "display": "Asthma",
        },
        format="json",
    )
    observation_response = client.post(
        "/api/clinical/observations/",
        {
            "patient_id": str(clinical_setup["patient"].pk),
            "status": "FINAL",
            "code": "8310-5",
            "system": "http://loinc.org",
            "display": "Body temperature",
            "effective_time": timezone.now().isoformat(),
            "value_quantity": "37.2",
            "value_unit": "Cel",
        },
        format="json",
    )

    assert condition_response.status_code == 201, condition_response.content
    assert observation_response.status_code == 201, observation_response.content
    assert ClinicalCondition.all_objects.filter(
        tenant=clinical_setup["tenant"], patient=clinical_setup["patient"], code="J45.9"
    ).exists()
    observation = ClinicalObservation.all_objects.get(pk=observation_response.json()["id"])
    assert str(observation.value_quantity) == "37.2000"
    assert observation.value_unit == "Cel"


def test_clinical_intake_rejects_cross_tenant_patients(clinical_setup, clinical_user, tenant_b):
    other_patient = Patient.all_objects.create(
        tenant=tenant_b,
        internal_reference_id="OTHER-PATIENT",
    )
    response = authenticated_client(clinical_user).post(
        "/api/clinical/encounters/",
        {
            "patient_id": str(other_patient.pk),
            "status": "IN_PROGRESS",
            "encounter_class": "AMB",
        },
        format="json",
    )

    assert response.status_code == 400
    assert not ClinicalEncounter.all_objects.filter(patient=other_patient).exists()


def test_clinical_intake_requires_write_capability(clinical_setup, cashier_user):
    response = authenticated_client(cashier_user).post(
        "/api/clinical/encounters/",
        {
            "patient_id": str(clinical_setup["patient"].pk),
            "status": "IN_PROGRESS",
            "encounter_class": "AMB",
        },
        format="json",
    )

    assert response.status_code == 403
