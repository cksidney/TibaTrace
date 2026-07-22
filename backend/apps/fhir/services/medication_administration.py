from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from apps.clinical.models import MedicationAdministrationRecord
from apps.fhir.services.search_utils import bounded_count, reference_id


class MedicationAdministrationLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[Any]:
        try:
            return MedicationAdministrationRecord.all_objects.get(id=resource_id, tenant_id=tenant_id)
        except ObjectDoesNotExist:
            return None

    @staticmethod
    def search(params, tenant_id: str):
        queryset = MedicationAdministrationRecord.all_objects.filter(tenant_id=tenant_id).select_related(
            "patient", "encounter", "performer"
        )
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("patient"):
            queryset = queryset.filter(patient_id=reference_id(params["patient"], "Patient"))
        if params.get("status"):
            queryset = queryset.filter(status__iexact=params["status"].replace("-", "_"))
        if params.get("medication"):
            queryset = queryset.filter(medication_name__icontains=params["medication"])
        if params.get("performer"):
            queryset = queryset.filter(
                performer_id=reference_id(params["performer"], "Practitioner")
            )
        if params.get("context"):
            queryset = queryset.filter(encounter_id=reference_id(params["context"], "Encounter"))
        if params.get("request"):
            queryset = queryset.filter(
                prescription_item_id=reference_id(params["request"], "MedicationRequest")
            )
        return list(queryset.order_by("-effective_time", "-created_at")[:bounded_count(params)])

    @staticmethod
    def process_domain_command(domain_command: dict, context: dict) -> Any:
        from apps.prescription.services.clinical_domain import ClinicalDomainService
        command = {**domain_command, "_operation": context.get("operation")}
        return ClinicalDomainService.process_medication_administration(command, context.get("tenant_id"))
