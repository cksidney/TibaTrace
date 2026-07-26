"""Browser sign-in for the HQ workspace.

A session cookie rather than a token in localStorage. HQ shows claims,
membership numbers and cash positions, and a token kept in localStorage is
readable by any script that gets into the page -- an HttpOnly cookie is not.
The trade is CSRF, which Django's session authentication already handles and
which is a solved problem; XSS token theft is not.

Three rules the endpoint keeps.

**It does not say whether a username exists.** A wrong username and a wrong
password return the same message after the same work. Otherwise the form is an
account enumerator, and a valid username plus a weak password is a much smaller
search than both together.

**It does not sign in a user with no workspace.** A user without a tenant sees
an empty workspace everywhere, which reads as data loss rather than as a
configuration problem, and generates a support call that takes an hour to
diagnose.

**It never logs the password.** Not on success, not on failure, not in an
exception. The serialiser marks it write-only so a validation error cannot echo
it back either.
"""
from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView


class SignInThrottle(AnonRateThrottle):
    """Bounds password guessing.

    A password field with no throttle is an offline attack conducted online.
    Scoped separately from other anonymous traffic so tightening it does not
    slow down anything else.
    """

    scope = "signin"


class SignInSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    # write_only, so a validation error cannot echo the password back into a
    # response body that ends up in a log or a browser console.
    password = serializers.CharField(max_length=256, write_only=True, trim_whitespace=False)


class SessionUserSerializer(serializers.Serializer):
    """Who the caller is. Deliberately small.

    Enough to render a header and decide what to show; not a user record. A
    sign-in response is the least authenticated thing a client holds, so it
    carries the least.
    """

    username = serializers.CharField()
    display_name = serializers.SerializerMethodField()
    tenant_id = serializers.SerializerMethodField()
    tenant_name = serializers.SerializerMethodField()
    is_platform_admin = serializers.BooleanField(default=False)

    def get_display_name(self, user) -> str:
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.username

    def get_tenant_id(self, user) -> str:
        return str(user.tenant_id) if user.tenant_id else ""

    def get_tenant_name(self, user) -> str:
        return getattr(user.tenant, "name", "") if user.tenant_id else ""


@method_decorator(ensure_csrf_cookie, name="get")
class SessionView(APIView):
    """The browser session: read it, create it, end it.

    GET is unauthenticated and always sets the CSRF cookie, because a client
    needs that token before it can post credentials. It reports whether anybody
    is signed in rather than refusing, so the app can decide between a sign-in
    form and a workspace without treating 401 as an error.
    """

    def get_permissions(self):
        if self.request.method in ("GET", "POST"):
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_throttles(self):
        return [SignInThrottle()] if self.request.method == "POST" else []

    def get(self, request):
        token = get_token(request)
        if not request.user.is_authenticated:
            return Response({"authenticated": False, "csrf_token": token})
        return Response(
            {
                "authenticated": True,
                "csrf_token": token,
                "user": SessionUserSerializer(request.user).data,
            }
        )

    def post(self, request):
        serializer = SignInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )

        if user is None or not user.is_active:
            # One message for a wrong username, a wrong password and a disabled
            # account. Distinguishing them turns the form into an account
            # enumerator.
            return Response(
                {"detail": "Username or password is incorrect."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.tenant_id and not user.is_platform_admin:
            # Signing this user in produces an empty workspace everywhere,
            # which reads as data loss rather than as a missing assignment.
            return Response(
                {
                    "detail": (
                        "This account is not assigned to a workspace. "
                        "An administrator must assign one before you can sign in."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        login(request, user)
        # Rotated by Django on login, which is what stops a session fixed
        # before authentication from carrying over afterwards.
        return Response(
            {
                "authenticated": True,
                "csrf_token": get_token(request),
                "user": SessionUserSerializer(user).data,
            }
        )

    def delete(self, request):
        logout(request)
        return Response({"authenticated": False}, status=status.HTTP_200_OK)
