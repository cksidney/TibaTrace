from django.db.models import Q

from apps.fhir.services.search_utils import bounded_count
from apps.medicines.models import Medicine


class MedicationLookupService:
    @staticmethod
    def _scope(tenant_id):
        return Medicine.all_objects.filter(Q(tenant_id=tenant_id) | Q(tenant__isnull=True, is_global=True))

    @classmethod
    def get_by_id(cls, resource_id, tenant_id):
        return cls._scope(tenant_id).filter(id=resource_id).first()

    @classmethod
    def search(cls, params, tenant_id):
        queryset = cls._scope(tenant_id)
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("code"):
            value = str(params["code"]).split("|")[-1]
            queryset = queryset.filter(Q(code=value) | Q(primary_barcode=value) | Q(gtin=value))
        if params.get("status"):
            queryset = queryset.filter(status=str(params["status"]).upper())
        return list(queryset.order_by("generic_name", "id")[: bounded_count(params)])
