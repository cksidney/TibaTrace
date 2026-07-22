from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.clinical.models import ClinicalObservation
from apps.clinical.services import ClinicalDomainService
from apps.fhir.exceptions import (
    FHIRBusinessRuleError,
    FHIRReferenceResolutionError,
    FHIRSecurityError,
    FHIRValidationError,
)
from apps.patients.models import Patient

pytestmark = pytest.mark.django_db


def _encounter_command(setup, **overrides):
    command = {
        "patient_id": str(setup["patient"].id),
        "status": "IN_PROGRESS",
        "encounter_class": "AMB",
        "organization_id": str(setup["organization"].id),
        "practitioner_id": str(setup["practitioner"].id),
        "start_time": (timezone.now() - timedelta(minutes=5)).isoformat(),
    }
    command.update(overrides)
    return command


def test_clinical_service_requires_tenant(clinical_setup):
    with pytest.raises(FHIRSecurityError):
        ClinicalDomainService.process_encounter(_encounter_command(clinical_setup), "")


def test_encounter_is_created_through_domain_service(clinical_setup):
    encounter = ClinicalDomainService.process_encounter(
        _encounter_command(clinical_setup), str(clinical_setup["tenant"].id)
    )
    assert encounter.patient == clinical_setup["patient"]
    assert encounter.organization == clinical_setup["organization"]


def test_finished_encounter_requires_end_time(clinical_setup):
    with pytest.raises(FHIRBusinessRuleError, match="end time"):
        ClinicalDomainService.process_encounter(
            _encounter_command(clinical_setup, status="FINISHED"),
            str(clinical_setup["tenant"].id),
        )


def test_encounter_end_cannot_precede_start(clinical_setup):
    now = timezone.now()
    with pytest.raises(FHIRBusinessRuleError, match="precede"):
        ClinicalDomainService.process_encounter(
            _encounter_command(
                clinical_setup,
                start_time=now.isoformat(),
                end_time=(now - timedelta(minutes=1)).isoformat(),
            ),
            str(clinical_setup["tenant"].id),
        )


def test_invalid_encounter_transition_is_blocked(clinical_setup):
    encounter = ClinicalDomainService.process_encounter(
        _encounter_command(clinical_setup), str(clinical_setup["tenant"].id)
    )
    with pytest.raises(FHIRBusinessRuleError, match="Invalid encounter"):
        ClinicalDomainService.process_encounter(
            _encounter_command(clinical_setup, id=str(encounter.id), status="PLANNED", _operation="update"),
            str(clinical_setup["tenant"].id),
        )


def test_cross_tenant_patient_reference_is_blocked(clinical_setup, tenant_b):
    patient_b = Patient.all_objects.create(tenant=tenant_b, internal_reference_id="PAT-B")
    command = _encounter_command(clinical_setup, patient_id=str(patient_b.id))
    with pytest.raises(FHIRReferenceResolutionError):
        ClinicalDomainService.process_encounter(command, str(clinical_setup["tenant"].id))


def test_condition_onset_cannot_be_future(clinical_setup):
    with pytest.raises(FHIRBusinessRuleError, match="future"):
        ClinicalDomainService.process_condition(
            {
                "patient_id": str(clinical_setup["patient"].id),
                "clinical_status": "ACTIVE",
                "verification_status": "CONFIRMED",
                "code": "DEMO",
                "onset_date": (timezone.now() + timedelta(days=1)).isoformat(),
            },
            str(clinical_setup["tenant"].id),
        )


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"value_quantity": "37.2", "value_unit": "Cel", "value_string": "normal"},
        {"value_quantity": "37.2"},
    ],
)
def test_observation_requires_exactly_one_supported_value(clinical_setup, values):
    command = {
        "patient_id": str(clinical_setup["patient"].id),
        "status": "FINAL",
        "code": "8310-5",
        "effective_time": timezone.now().isoformat(),
        **values,
    }
    with pytest.raises(FHIRBusinessRuleError):
        ClinicalDomainService.process_observation(command, str(clinical_setup["tenant"].id))


def test_observation_patient_is_immutable(clinical_setup, tenant_b):
    observation = ClinicalDomainService.process_observation(
        {
            "patient_id": str(clinical_setup["patient"].id),
            "status": "FINAL",
            "code": "8310-5",
            "effective_time": timezone.now().isoformat(),
            "value_quantity": "37.2",
            "value_unit": "Cel",
        },
        str(clinical_setup["tenant"].id),
    )
    other = Patient.all_objects.create(tenant=clinical_setup["tenant"], internal_reference_id="PAT-OTHER")
    with pytest.raises(FHIRBusinessRuleError, match="cannot be changed"):
        ClinicalDomainService.process_observation(
            {
                "id": str(observation.id),
                "_operation": "update",
                "patient_id": str(other.id),
                "status": "AMENDED",
                "code": "8310-5",
                "effective_time": timezone.now().isoformat(),
                "value_string": "amended",
            },
            str(clinical_setup["tenant"].id),
        )


def test_diagnostic_results_must_match_patient(clinical_setup):
    other = Patient.all_objects.create(tenant=clinical_setup["tenant"], internal_reference_id="PAT-OTHER")
    observation = ClinicalObservation.all_objects.create(
        tenant=clinical_setup["tenant"],
        patient=other,
        status="FINAL",
        code="OBS",
        effective_time=timezone.now(),
        value_string="result",
    )
    with pytest.raises(FHIRBusinessRuleError, match="report patient"):
        ClinicalDomainService.process_diagnostic_report(
            {
                "patient_id": str(clinical_setup["patient"].id),
                "status": "FINAL",
                "code": "REPORT",
                "effective_time": timezone.now().isoformat(),
                "observations": [str(observation.id)],
            },
            str(clinical_setup["tenant"].id),
        )


@pytest.mark.parametrize("url", ["file:///tmp/report.pdf", "http://example.test/report.pdf", "javascript:bad"])
def test_clinical_document_requires_secure_object_url(clinical_setup, url):
    with pytest.raises(FHIRBusinessRuleError):
        ClinicalDomainService.process_document_reference(
            {
                "patient_id": str(clinical_setup["patient"].id),
                "status": "CURRENT",
                "object_url": url,
                "content_type": "application/pdf",
            },
            str(clinical_setup["tenant"].id),
        )


def test_clinical_document_rejects_invalid_hash(clinical_setup):
    with pytest.raises(FHIRValidationError, match="SHA-256"):
        ClinicalDomainService.process_document_reference(
            {
                "patient_id": str(clinical_setup["patient"].id),
                "status": "CURRENT",
                "object_url": "https://documents.example.test/report.pdf",
                "content_type": "application/pdf",
                "hash_sha256": "bad",
            },
            str(clinical_setup["tenant"].id),
        )


def test_not_done_administration_requires_reason(clinical_setup):
    with pytest.raises(FHIRBusinessRuleError, match="reason"):
        ClinicalDomainService.process_medication_administration(
            {
                "patient_id": str(clinical_setup["patient"].id),
                "status": "NOT_DONE",
                "medication_name": "Demo medicine",
                "effective_time": timezone.now().isoformat(),
            },
            str(clinical_setup["tenant"].id),
        )
