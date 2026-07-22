from apps.core.api.viewsets import TenantModelViewSet
from apps.patients.api.serializers import PatientSerializer
from apps.patients.models import Patient


class PatientViewSet(TenantModelViewSet):
    queryset = Patient.all_objects.all()
    serializer_class = PatientSerializer
    read_capability = "patients.read"
    write_capability = "patients.write"
    search_fields = ("internal_reference_id", "first_name", "last_name", "phone")
