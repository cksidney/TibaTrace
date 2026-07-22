from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from apps.clinical.models import ClinicalDocument
from apps.fhir.services.search_utils import bounded_count, reference_id


class DocumentReferenceLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[Any]:
        try:
            return ClinicalDocument.all_objects.get(id=resource_id, tenant_id=tenant_id)
        except ObjectDoesNotExist:
            return None

    @staticmethod
    def search(params, tenant_id: str):
        queryset = ClinicalDocument.all_objects.filter(tenant_id=tenant_id).select_related(
            "patient", "author", "encounter"
        )
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("patient"):
            queryset = queryset.filter(patient_id=reference_id(params["patient"], "Patient"))
        if params.get("status"):
            queryset = queryset.filter(status__iexact=params["status"].replace("-", "_"))
        if params.get("type"):
            queryset = queryset.filter(doc_type=params["type"])
        if params.get("category"):
            queryset = queryset.filter(category=params["category"])
        if params.get("author"):
            queryset = queryset.filter(author_id=reference_id(params["author"], "Practitioner"))
        return list(queryset.order_by("-created_at")[:bounded_count(params)])

    @staticmethod
    def process_domain_command(domain_command: dict, context: dict) -> Any:
        from apps.prescription.services.clinical_domain import ClinicalDomainService
        command = {**domain_command, "_operation": context.get("operation")}
        return ClinicalDomainService.process_document_reference(command, context.get("tenant_id"))
