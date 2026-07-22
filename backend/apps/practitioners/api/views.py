from apps.core.api.viewsets import TenantModelViewSet
from apps.practitioners.api.serializers import PractitionerSerializer
from apps.practitioners.models import Practitioner


class PractitionerViewSet(TenantModelViewSet):
    queryset = Practitioner.all_objects.all()
    serializer_class = PractitionerSerializer
    read_capability = "practitioners.read"
    write_capability = "practitioners.write"
    search_fields = ("first_name", "last_name", "email")
