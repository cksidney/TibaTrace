"""The pharmacy network API.

Read-only over the collection, with every state change routed through a named
service action. There is deliberately no generic PATCH on status: the whole
point of the module is that a pharmacy's state moves only through rules that
check a licence and record who decided.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.pharmacy_network.api.serializers import (
    BeginOnboardingSerializer,
    OptionalReasonSerializer,
    PharmacyProfileSerializer,
    PharmacySerializer,
    ReasonSerializer,
    RegisterPharmacySerializer,
    TenantLifecycleEventSerializer,
)
from apps.pharmacy_network.models import TenantLifecycleEvent
from apps.pharmacy_network.services import (
    PharmacyOnboardingService,
    TenantLifecycleService,
)
from apps.tenancy.models import Tenant


def _errors(exc: DjangoValidationError) -> dict:
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"detail": exc.messages if hasattr(exc, "messages") else [str(exc)]}


class PharmacyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PharmacySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        base = Tenant.objects.select_related("pharmacy_profile").order_by("name", "id")
        if user.is_superuser or user.is_platform_admin:
            return base
        # An operator sees their own pharmacy and no other. Terminated tenants
        # are not hidden from their own staff: somebody has to be able to see
        # why they cannot work.
        if user.tenant_id:
            return base.filter(pk=user.tenant_id)
        return base.none()

    def _require_platform_admin(self):
        user = self.request.user
        if not (user.is_superuser or user.is_platform_admin):
            raise PermissionDenied(
                "Pharmacy network administration is restricted to platform administrators."
            )

    def _run(self, operation):
        """Run a service call and translate its refusal into a 400.

        A refused transition is the service working, not an error in the
        request's shape, so it reports the service's own message rather than a
        generic validation failure.
        """
        try:
            tenant = operation()
        except DjangoValidationError as exc:
            return Response(_errors(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(tenant).data)

    def create(self, request, *args, **kwargs):
        self._require_platform_admin()
        serializer = RegisterPharmacySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tenant = PharmacyOnboardingService.register_prospect(
                actor=request.user, **serializer.validated_data
            )
        except DjangoValidationError as exc:
            return Response(_errors(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(
            self.get_serializer(tenant).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["patch"], url_path="profile")
    def profile(self, request, pk=None):
        """Update the regulatory and commercial record.

        Separate from the lifecycle: recording a renewed licence is routine
        maintenance, and forcing it through a state transition would mean a
        pharmacy had to be suspended to update its paperwork.
        """
        self._require_platform_admin()
        tenant = self.get_object()
        profile = getattr(tenant, "pharmacy_profile", None)
        if profile is None:
            return Response(
                {"detail": "This pharmacy has no profile record."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = PharmacyProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        try:
            updated.full_clean()
        except DjangoValidationError as exc:
            return Response(_errors(exc), status=status.HTTP_400_BAD_REQUEST)
        updated.save()
        tenant.refresh_from_db()
        return Response(self.get_serializer(tenant).data)

    @action(detail=True, methods=["post"], url_path="begin-onboarding")
    def begin_onboarding(self, request, pk=None):
        self._require_platform_admin()
        serializer = BeginOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.get_object()
        return self._run(
            lambda: PharmacyOnboardingService.begin_onboarding(
                tenant=tenant, actor=request.user, **serializer.validated_data
            )
        )

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        self._require_platform_admin()
        serializer = OptionalReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.get_object()
        return self._run(
            lambda: PharmacyOnboardingService.activate(
                tenant=tenant, actor=request.user, **serializer.validated_data
            )
        )

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        self._require_platform_admin()
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.get_object()
        return self._run(
            lambda: TenantLifecycleService.suspend(
                tenant=tenant, actor=request.user, **serializer.validated_data
            )
        )

    @action(detail=True, methods=["post"])
    def reinstate(self, request, pk=None):
        self._require_platform_admin()
        serializer = OptionalReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.get_object()
        return self._run(
            lambda: TenantLifecycleService.reinstate(
                tenant=tenant, actor=request.user, **serializer.validated_data
            )
        )

    @action(detail=True, methods=["post"])
    def terminate(self, request, pk=None):
        self._require_platform_admin()
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.get_object()
        return self._run(
            lambda: TenantLifecycleService.terminate(
                tenant=tenant, actor=request.user, **serializer.validated_data
            )
        )

    @action(detail=True, methods=["get"], url_path="lifecycle")
    def lifecycle(self, request, pk=None):
        """Every transition this pharmacy has been through.

        Readable by the pharmacy's own staff as well as platform
        administrators: being told why you were suspended is not privileged
        information to the suspended party.
        """
        tenant = self.get_object()
        events = TenantLifecycleEvent.all_objects.filter(
            tenant_id=tenant.pk
        ).select_related("actor")
        return Response(TenantLifecycleEventSerializer(events, many=True).data)
