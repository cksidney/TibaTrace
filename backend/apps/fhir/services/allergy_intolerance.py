from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from apps.fhir.services.search_utils import bounded_count, reference_id
from apps.patients.models import PatientAllergy


class AllergyIntoleranceLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[Any]:
        try:
            return PatientAllergy.all_objects.get(id=resource_id, tenant_id=tenant_id)
        except ObjectDoesNotExist:
            return None

    @staticmethod
    def search(params, tenant_id: str):
        queryset = PatientAllergy.all_objects.filter(tenant_id=tenant_id).select_related("patient")
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("patient"):
            queryset = queryset.filter(patient_id=reference_id(params["patient"], "Patient"))
        if params.get("clinical-status"):
            active = str(params["clinical-status"]).lower() == "active"
            queryset = queryset.filter(is_active=active)
        if params.get("code"):
            queryset = queryset.filter(allergen_name__icontains=params["code"])
        if params.get("criticality"):
            severity_by_criticality = {
                "low": PatientAllergy.SEVERITY_INFO,
                "high": PatientAllergy.SEVERITY_WARNING,
                "unable-to-assess": PatientAllergy.SEVERITY_HARD_STOP,
            }
            severity = severity_by_criticality.get(str(params["criticality"]).lower())
            queryset = queryset.none() if not severity else queryset.filter(severity=severity)
        return list(queryset.order_by("-created_at")[:bounded_count(params)])

    @staticmethod
    def process_domain_command(domain_command: dict, context: dict) -> Any:
        tenant_id = context.get('tenant_id')
        if not tenant_id:
            raise ValueError("Tenant ID is missing in context.")

        from apps.prescription.services.clinical_domain import ClinicalDomainService
        command = {**domain_command, "_operation": context.get("operation")}
        return ClinicalDomainService.process_patient_allergy(command, tenant_id)
