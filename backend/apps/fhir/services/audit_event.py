from typing import Optional

from apps.fhir.services.search_utils import bounded_count
from apps.prescription.models import PrescriptionAudit


class AuditEventLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[PrescriptionAudit]:
        return PrescriptionAudit.all_objects.filter(
            id=resource_id,
            tenant_id=tenant_id,
            prescription__tenant_id=tenant_id,
        ).first()

    @staticmethod
    def search(params, tenant_id):
        queryset = PrescriptionAudit.all_objects.filter(tenant_id=tenant_id)
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("agent"):
            queryset = queryset.filter(user_id=str(params["agent"]).split("/")[-1])
        if params.get("entity"):
            queryset = queryset.filter(prescription_id=str(params["entity"]).split("/")[-1])
        if params.get("type"):
            queryset = queryset.filter(event_type__iexact=params["type"])
        return list(queryset.order_by("-created_at")[: bounded_count(params)])
