from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.identity.api.session_views import SessionView
from apps.identity.api.views import (
    CapabilityMatrixView,
    MeView,
    RoleListView,
    RoleViewSet,
    ServiceAccountViewSet,
    UserRoleViewSet,
    UserViewSet,
)
from apps.identity.authentication import DawaTraceTokenSerializer


class DawaTraceTokenView(TokenObtainPairView):
    serializer_class = DawaTraceTokenSerializer


router = DefaultRouter()
router.register("users", UserViewSet, basename="identity-user")
router.register("roles-detail", RoleViewSet, basename="identity-role-detail")
router.register("user-roles", UserRoleViewSet, basename="identity-user-role")
router.register("service-accounts", ServiceAccountViewSet, basename="identity-service-account")

urlpatterns = [
    path("token/", DawaTraceTokenView.as_view(), name="identity-token"),
    path("token/refresh/", TokenRefreshView.as_view(), name="identity-token-refresh"),
    path("session/", SessionView.as_view(), name="identity-session"),
    path("me/", MeView.as_view(), name="identity-me"),
    path("roles/", RoleListView.as_view(), name="identity-roles"),
    path("matrix/", CapabilityMatrixView.as_view(), name="identity-capability-matrix"),
    path("", include(router.urls)),
]
