from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from apps.fhir.services.search_utils import bounded_count, reference_id
from apps.patients.models import PatientMedication


class MedicationStatementLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[Any]:
        try:
            return PatientMedication.all_objects.get(id=resource_id, tenant_id=tenant_id)
        except ObjectDoesNotExist:
            return None

    @staticmethod
    def search(params, tenant_id):
        queryset = PatientMedication.all_objects.filter(tenant_id=tenant_id)
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("subject"):
            queryset = queryset.filter(patient_id=reference_id(params["subject"], "Patient"))
        if params.get("status"):
            queryset = queryset.filter(status=str(params["status"]).upper())
        if params.get("medication"):
            queryset = queryset.filter(medicine_id=reference_id(params["medication"], "Medication"))
        return list(queryset.order_by("-created_at")[: bounded_count(params)])

    @staticmethod
    def process_domain_command(domain_command: dict, context: dict) -> Any:
        tenant_id = context.get('tenant_id')
        if not tenant_id:
            raise ValueError("Tenant ID is missing in context.")

        from apps.prescription.services.clinical_domain import ClinicalDomainService
        command = {**domain_command, "_operation": context.get("operation")}
        return ClinicalDomainService.process_medication_statement(command, tenant_id)
