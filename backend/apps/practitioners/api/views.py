from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.api.viewsets import TenantModelViewSet
from apps.practitioners.api.serializers import (
    PractitionerSerializer,
    PrescriberVerificationSerializer,
)
from apps.practitioners.models import Practitioner
from apps.practitioners.services import PrescriberGovernanceService


class PractitionerViewSet(TenantModelViewSet):
    queryset = Practitioner.all_objects.prefetch_related("licences", "roles")
    serializer_class = PractitionerSerializer
    read_capability = "practitioners.read"
    write_capability = "practitioners.write"
    search_fields = (
        "first_name",
        "last_name",
        "professional_name",
        "registration_number",
        "email",
    )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Practitioner.all_objects.none()
        return self.queryset.filter(tenant_id=self.request.tenant_id)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        serializer = PrescriberVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        practitioner = PrescriberGovernanceService.verify(
            practitioner=self.get_object(),
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(PractitionerSerializer(practitioner).data)
