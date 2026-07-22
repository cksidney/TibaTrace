from apps.core.api.viewsets import TenantModelViewSet
from apps.organizations.api.serializers import LocationSerializer, OrganizationSerializer
from apps.organizations.models import Location, Organization


class OrganizationViewSet(TenantModelViewSet):
    queryset = Organization.all_objects.all()
    serializer_class = OrganizationSerializer
    read_capability = "organizations.read"
    write_capability = "organizations.write"


class LocationViewSet(TenantModelViewSet):
    queryset = Location.all_objects.all()
    serializer_class = LocationSerializer
    read_capability = "organizations.read"
    write_capability = "organizations.write"
