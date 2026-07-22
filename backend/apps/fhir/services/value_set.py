from typing import Any, Optional

from django.db.models import Q

from apps.fhir.services.search_utils import bounded_count
from apps.terminology.models import FHIRValueSetRegistration


class ValueSetLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[Any]:
        return FHIRValueSetRegistration.all_objects.select_related("version").filter(
            Q(tenant_id=tenant_id) | Q(tenant__isnull=True, version__is_global=True),
            id=resource_id,
        ).first()

    @staticmethod
    def search(params, tenant_id: str):
        queryset = FHIRValueSetRegistration.all_objects.filter(
            Q(tenant_id=tenant_id) | Q(tenant__isnull=True, version__is_global=True)
        ).select_related("version")
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("url"):
            queryset = queryset.filter(url=params["url"])
        if params.get("version"):
            queryset = queryset.filter(version__version=params["version"])
        if params.get("name"):
            queryset = queryset.filter(name__icontains=params["name"])
        if params.get("status"):
            queryset = queryset.filter(version__status__iexact=params["status"])
        return list(queryset.order_by("url", "-version__version")[:bounded_count(params)])

    @staticmethod
    def process_domain_command(domain_command: dict, context: dict) -> Any:
        raise NotImplementedError("ValueSet modification via FHIR is not supported.")
