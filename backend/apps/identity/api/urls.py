from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.identity.api.session_views import SessionView
from apps.identity.api.views import MeView, RoleListView
from apps.identity.authentication import DawaTraceTokenSerializer


class DawaTraceTokenView(TokenObtainPairView):
    serializer_class = DawaTraceTokenSerializer


urlpatterns = [
    path("token/", DawaTraceTokenView.as_view(), name="identity-token"),
    path("token/refresh/", TokenRefreshView.as_view(), name="identity-token-refresh"),
    path("session/", SessionView.as_view(), name="identity-session"),
    path("me/", MeView.as_view(), name="identity-me"),
    path("roles/", RoleListView.as_view(), name="identity-roles"),
]
