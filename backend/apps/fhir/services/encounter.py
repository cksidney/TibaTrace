from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from apps.clinical.models import ClinicalEncounter
from apps.fhir.services.search_utils import bounded_count, reference_id


class EncounterLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[Any]:
        try:
            return ClinicalEncounter.all_objects.get(id=resource_id, tenant_id=tenant_id)
        except ObjectDoesNotExist:
            return None

    @staticmethod
    def search(params, tenant_id: str):
        queryset = ClinicalEncounter.all_objects.filter(tenant_id=tenant_id).select_related(
            "patient", "organization", "location", "practitioner"
        )
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("patient"):
            queryset = queryset.filter(patient_id=reference_id(params["patient"], "Patient"))
        if params.get("status"):
            queryset = queryset.filter(status__iexact=params["status"].replace("-", "_"))
        if params.get("class"):
            queryset = queryset.filter(encounter_class=params["class"])
        if params.get("service-provider"):
            queryset = queryset.filter(
                organization_id=reference_id(params["service-provider"], "Organization")
            )
        if params.get("participant"):
            queryset = queryset.filter(
                practitioner_id=reference_id(params["participant"], "Practitioner")
            )
        return list(queryset.order_by("-start_time", "-created_at")[:bounded_count(params)])

    @staticmethod
    def process_domain_command(domain_command: dict, context: dict) -> Any:
        from apps.prescription.services.clinical_domain import ClinicalDomainService
        command = {**domain_command, "_operation": context.get("operation")}
        return ClinicalDomainService.process_encounter(command, context.get("tenant_id"))
