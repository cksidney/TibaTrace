from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from apps.clinical.models import ClinicalCondition
from apps.fhir.services.search_utils import bounded_count, reference_id


class ConditionLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[Any]:
        try:
            return ClinicalCondition.all_objects.get(id=resource_id, tenant_id=tenant_id)
        except ObjectDoesNotExist:
            return None

    @staticmethod
    def search(params, tenant_id: str):
        queryset = ClinicalCondition.all_objects.filter(tenant_id=tenant_id).select_related("patient", "encounter")
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("patient"):
            queryset = queryset.filter(patient_id=reference_id(params["patient"], "Patient"))
        if params.get("clinical-status"):
            queryset = queryset.filter(clinical_status__iexact=params["clinical-status"].replace("-", "_"))
        if params.get("verification-status"):
            queryset = queryset.filter(verification_status__iexact=params["verification-status"].replace("-", "_"))
        if params.get("category"):
            queryset = queryset.filter(category=params["category"])
        if params.get("code"):
            queryset = queryset.filter(code=params["code"])
        if params.get("encounter"):
            queryset = queryset.filter(encounter_id=reference_id(params["encounter"], "Encounter"))
        return list(queryset.order_by("-recorded_date")[:bounded_count(params)])

    @staticmethod
    def process_domain_command(domain_command: dict, context: dict) -> Any:
        from apps.prescription.services.clinical_domain import ClinicalDomainService
        command = {**domain_command, "_operation": context.get("operation")}
        return ClinicalDomainService.process_condition(command, context.get("tenant_id"))
