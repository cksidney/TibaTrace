from drf_spectacular.utils import extend_schema
from rest_framework import generics, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import TenantCapabilityPermission, TenantRequired
from apps.identity.api.serializers import (
    RoleSerializer,
    ServiceAccountSerializer,
    UserDetailSerializer,
    UserRoleSerializer,
    UserSummarySerializer,
)
from apps.identity.models import Role, ServiceAccount, User, UserRole


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


class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, TenantRequired, TenantCapabilityPermission]
    read_capability = "identity.manage"
    serializer_class = RoleSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Role.all_objects.none()
        tenant_id = getattr(self.request, "tenant_id", None) or self.request.user.tenant_id
        if not tenant_id:
            return Role.all_objects.none()
        return Role.all_objects.filter(tenant_id=tenant_id).order_by("name")


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, TenantRequired, TenantCapabilityPermission]
    read_capability = "identity.manage"
    serializer_class = UserDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        tenant_id = getattr(self.request, "tenant_id", None) or self.request.user.tenant_id
        if not tenant_id:
            return User.objects.none()
        return User.objects.filter(tenant_id=tenant_id).order_by("username")


class UserRoleViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, TenantRequired, TenantCapabilityPermission]
    read_capability = "identity.manage"
    serializer_class = UserRoleSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return UserRole.all_objects.none()
        tenant_id = getattr(self.request, "tenant_id", None) or self.request.user.tenant_id
        if not tenant_id:
            return UserRole.all_objects.none()
        return UserRole.all_objects.filter(tenant_id=tenant_id).select_related("user", "role").order_by("-created_at")


class ServiceAccountViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, TenantRequired, TenantCapabilityPermission]
    read_capability = "identity.manage"
    serializer_class = ServiceAccountSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ServiceAccount.all_objects.none()
        tenant_id = getattr(self.request, "tenant_id", None) or self.request.user.tenant_id
        if not tenant_id:
            return ServiceAccount.all_objects.none()
        return ServiceAccount.all_objects.filter(tenant_id=tenant_id).order_by("code")


class CapabilityMatrixView(APIView):
    permission_classes = [IsAuthenticated, TenantRequired, TenantCapabilityPermission]
    read_capability = "identity.manage"

    def get(self, request):
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        roles = Role.all_objects.filter(tenant_id=tenant_id, is_active=True) if tenant_id else Role.all_objects.none()
        users = User.objects.filter(tenant_id=tenant_id, is_active=True) if tenant_id else User.objects.none()
        service_accounts = ServiceAccount.all_objects.filter(tenant_id=tenant_id, is_active=True) if tenant_id else ServiceAccount.all_objects.none()

        matrix = {
            "tenant_id": str(tenant_id or ""),
            "roles": [
                {
                    "id": str(r.id),
                    "code": r.code,
                    "name": r.name,
                    "capabilities": r.capabilities or [],
                    "is_system": r.is_system,
                    "assigned_users_count": UserRole.all_objects.filter(
                        tenant_id=tenant_id,
                        role=r,
                        is_active=True,
                    ).count(),
                }
                for r in roles
            ],
            "users": [
                {
                    "id": str(u.id),
                    "username": u.username,
                    "email": u.email,
                    "is_platform_admin": u.is_platform_admin,
                    "is_superuser": u.is_superuser,
                    "assigned_roles": [
                        assignment.role.code
                        for assignment in UserRole.all_objects.filter(
                            tenant_id=tenant_id,
                            user=u,
                            is_active=True,
                        ).select_related("role")
                    ],
                    "effective_capabilities": sorted(list(u.effective_capabilities(tenant_id=tenant_id))),
                }
                for u in users
            ],
            "service_accounts": [
                {
                    "id": str(s.id),
                    "code": s.code,
                    "display_name": s.display_name,
                    "capabilities": s.capabilities or [],
                    "fingerprint": s.credential_fingerprint,
                }
                for s in service_accounts
            ],
        }
        return Response(matrix)
