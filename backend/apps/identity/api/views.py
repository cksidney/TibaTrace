from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import TenantRequired
from apps.identity.api.serializers import RoleSerializer, UserSummarySerializer
from apps.identity.models import Role


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserSummarySerializer)
    def get(self, request):
        return Response(UserSummarySerializer(request.user).data)


class RoleListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, TenantRequired]
    serializer_class = RoleSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Role.all_objects.none()
        return Role.all_objects.filter(tenant_id=self.request.tenant_id, is_active=True).order_by("name")
