from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import TenantCapabilityPermission, TenantRequired
from apps.identity.api.serializers import (
    PasswordResetAdminSerializer,
    RoleCreateSerializer,
    RoleSerializer,
    RoleUpdateSerializer,
    ServiceAccountSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserRoleAssignmentSerializer,
    UserRoleSerializer,
    UserSummarySerializer,
)
from apps.identity.capability_catalogue import catalogue_for_tenant
from apps.identity.models import Role, ServiceAccount, User, UserRole
from apps.identity.services import (
    ACCOUNT_STATUS_DISABLED,
    ACCOUNT_STATUS_SUSPENDED,
    UserAdministrationService,
    account_status_for,
)


class IdentityUserPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


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


class RoleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, TenantRequired, TenantCapabilityPermission]
    read_capability = "identity.manage"
    write_capability = "identity.manage"
    serializer_class = RoleSerializer
    http_method_names = ["get", "head", "options", "post", "patch"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Role.all_objects.none()
        tenant_id = getattr(self.request, "tenant_id", None) or self.request.user.tenant_id
        if not tenant_id:
            return Role.all_objects.none()
        return Role.all_objects.filter(tenant_id=tenant_id).order_by("name")

    def list(self, request, *args, **kwargs):
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        if tenant_id:
            UserAdministrationService.ensure_default_tenant_roles(tenant_id=tenant_id)
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        payload = RoleCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        try:
            role = UserAdministrationService.create_role(
                tenant_id=tenant_id,
                **payload.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            RoleSerializer(role, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        role = self.get_object()
        payload = RoleUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        try:
            role = UserAdministrationService.update_role(role=role, **payload.validated_data)
        except DjangoValidationError as exc:
            return Response(
                exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(RoleSerializer(role, context={"request": request}).data)


class UserViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, TenantRequired, TenantCapabilityPermission]
    read_capability = "identity.manage"
    write_capability = "identity.manage"
    serializer_class = UserDetailSerializer
    pagination_class = IdentityUserPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        tenant_id = getattr(self.request, "tenant_id", None) or self.request.user.tenant_id
        if not tenant_id:
            return User.objects.none()
        queryset = User.objects.filter(tenant_id=tenant_id).order_by("username")

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        category = (self.request.query_params.get("category") or "").strip().upper()
        if category == "ACTIVE":
            queryset = queryset.filter(is_active=True)
        elif category == "SUSPENDED":
            # Metadata-driven suspend; fall back to inactive without DISABLED mark.
            suspended_ids = [
                user.pk
                for user in queryset.filter(is_active=False)
                if account_status_for(user) == ACCOUNT_STATUS_SUSPENDED
            ]
            queryset = queryset.filter(pk__in=suspended_ids)
        elif category == "DISABLED":
            disabled_ids = [
                user.pk
                for user in queryset.filter(is_active=False)
                if account_status_for(user) == ACCOUNT_STATUS_DISABLED
            ]
            queryset = queryset.filter(pk__in=disabled_ids)
        elif category == "ADMIN":
            queryset = queryset.filter(Q(is_platform_admin=True) | Q(is_superuser=True))
        elif category.startswith("ROLE:"):
            role_code = category.split(":", 1)[1].strip()
            if role_code:
                queryset = queryset.filter(
                    role_assignments__tenant_id=tenant_id,
                    role_assignments__is_active=True,
                    role_assignments__role__code=role_code,
                ).distinct()

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = UserDetailSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        user = self.get_object()
        return Response(UserDetailSerializer(user, context={"request": request}).data)

    def create(self, request, *args, **kwargs):
        payload = UserCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        try:
            user, temporary_password = UserAdministrationService.create_user(
                tenant_id=tenant_id,
                **payload.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        body = UserDetailSerializer(user, context={"request": request}).data
        body["temporary_password"] = temporary_password
        return Response(body, status=status.HTTP_201_CREATED)

    def _mutate_status(self, request, mutator):
        user = self.get_object()
        if user.pk == request.user.pk:
            return Response(
                {"detail": "You cannot change the status of your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            user = mutator(user=user)
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UserDetailSerializer(user, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._mutate_status(request, UserAdministrationService.activate)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._mutate_status(request, UserAdministrationService.suspend)

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        return self._mutate_status(request, UserAdministrationService.disable)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        payload = PasswordResetAdminSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            user, temporary_password = UserAdministrationService.reset_password(
                user=user,
                password=payload.validated_data.get("password") or None,
            )
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        body = UserDetailSerializer(user, context={"request": request}).data
        body["temporary_password"] = temporary_password
        return Response(body)

    @action(detail=True, methods=["post"], url_path="set-roles")
    def set_roles(self, request, pk=None):
        user = self.get_object()
        payload = UserRoleAssignmentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        try:
            UserAdministrationService.set_roles(
                user=user,
                tenant_id=tenant_id,
                role_ids=payload.validated_data["role_ids"],
            )
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        user.refresh_from_db()
        return Response(UserDetailSerializer(user, context={"request": request}).data)


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
            "catalogue": catalogue_for_tenant(tenant_id),
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
