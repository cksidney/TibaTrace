from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from apps.clinical.models import ClinicalDiagnosticReport
from apps.fhir.services.search_utils import bounded_count, reference_id


class DiagnosticReportLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[Any]:
        try:
            return ClinicalDiagnosticReport.all_objects.prefetch_related('observations').get(
                id=resource_id,
                tenant_id=tenant_id,
            )
        except ObjectDoesNotExist:
            return None

    @staticmethod
    def search(params, tenant_id: str):
        queryset = ClinicalDiagnosticReport.all_objects.filter(tenant_id=tenant_id).select_related(
            "patient", "encounter"
        ).prefetch_related("observations")
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("patient"):
            queryset = queryset.filter(patient_id=reference_id(params["patient"], "Patient"))
        if params.get("status"):
            queryset = queryset.filter(status__iexact=params["status"].replace("-", "_"))
        if params.get("category"):
            queryset = queryset.filter(category=params["category"])
        if params.get("code"):
            queryset = queryset.filter(code=params["code"])
        if params.get("result"):
            queryset = queryset.filter(
                observations__id=reference_id(params["result"], "Observation")
            )
        if params.get("encounter"):
            queryset = queryset.filter(encounter_id=reference_id(params["encounter"], "Encounter"))
        return list(queryset.distinct().order_by("-effective_time", "-created_at")[:bounded_count(params)])

    @staticmethod
    def process_domain_command(domain_command: dict, context: dict) -> Any:
        from apps.prescription.services.clinical_domain import ClinicalDomainService
        command = {**domain_command, "_operation": context.get("operation")}
        return ClinicalDomainService.process_diagnostic_report(command, context.get("tenant_id"))
