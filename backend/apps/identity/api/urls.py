from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.identity.api.mfa_views import MfaView
from apps.identity.api.session_views import (
    PasswordChangeView,
    PasswordForgotView,
    PasswordResetConfirmView,
    SessionView,
    SignInThrottle,
)
from apps.identity.api.views import (
    CapabilityMatrixView,
    MeView,
    RoleListView,
    RoleViewSet,
    ServiceAccountViewSet,
    UserRoleViewSet,
    UserViewSet,
)
from apps.identity.authentication import DawaTraceTokenSerializer, MfaTokenRefreshSerializer


class DawaTraceTokenView(TokenObtainPairView):
    serializer_class = DawaTraceTokenSerializer
    throttle_classes = [SignInThrottle]


class MfaTokenRefreshView(TokenRefreshView):
    serializer_class = MfaTokenRefreshSerializer


router = DefaultRouter()
router.register("users", UserViewSet, basename="identity-user")
router.register("roles-detail", RoleViewSet, basename="identity-role-detail")
router.register("user-roles", UserRoleViewSet, basename="identity-user-role")
router.register("service-accounts", ServiceAccountViewSet, basename="identity-service-account")

urlpatterns = [
    path("token/", DawaTraceTokenView.as_view(), name="identity-token"),
    path("token/refresh/", MfaTokenRefreshView.as_view(), name="identity-token-refresh"),
    path("session/", SessionView.as_view(), name="identity-session"),
    path("mfa/<str:operation>/", MfaView.as_view(), name="identity-mfa"),
    path("password/forgot/", PasswordForgotView.as_view(), name="identity-password-forgot"),
    path("password/reset/", PasswordResetConfirmView.as_view(), name="identity-password-reset"),
    path("password/change/", PasswordChangeView.as_view(), name="identity-password-change"),
    path("me/", MeView.as_view(), name="identity-me"),
    path("roles/", RoleListView.as_view(), name="identity-roles"),
    path("matrix/", CapabilityMatrixView.as_view(), name="identity-capability-matrix"),
    path("", include(router.urls)),
]
