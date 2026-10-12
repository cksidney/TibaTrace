from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api.viewsets import TenantModelViewSet
from apps.practitioners.api.serializers import (
    ControlledAuthorityActionSerializer,
    PractitionerSerializer,
    PrescriberVerificationSerializer,
)
from apps.practitioners.models import Practitioner
from apps.practitioners.services import (
    PractitionerRegistrationService,
    PrescriberGovernanceService,
)
from apps.tenancy.models import Tenant


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

    def get_permissions(self):
        self.write_capability = (
            "prescribers.verify"
            if self.action in {"verify", "controlled_authority"}
            else "practitioners.write"
        )
        return super().get_permissions()

    def perform_create(self, serializer):
        values = dict(serializer.validated_data)
        try:
            serializer.instance = PractitionerRegistrationService.register_practitioner(
                tenant=Tenant.objects.get(pk=self.request.tenant_id),
                actor=self.request.user,
                **values,
            )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages) from exc
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        serializer = PrescriberVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            practitioner = PrescriberGovernanceService.verify(
                practitioner=self.get_object(),
                actor=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages) from exc
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc
        return Response(PractitionerSerializer(practitioner).data)

    @action(detail=True, methods=["post"], url_path="controlled-authority")
    def controlled_authority(self, request, pk=None):
        serializer = ControlledAuthorityActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if values["action"] == "GRANT" and not values.get("evidence_reference", "").strip():
            raise ValidationError({"evidence_reference": "Granting authority requires a regulator or approval evidence reference."})
        practitioner = self.get_object()
        try:
            if values["action"] == "GRANT":
                practitioner = PractitionerRegistrationService.grant_controlled_medicine_authority(
                    practitioner=practitioner,
                    actor=request.user,
                    reason=values["reason"],
                    evidence_reference=values.get("evidence_reference", ""),
                )
            else:
                practitioner = PractitionerRegistrationService.revoke_controlled_medicine_authority(
                    practitioner=practitioner,
                    actor=request.user,
                    reason=values["reason"],
                )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages) from exc
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc
        return Response(PractitionerSerializer(practitioner).data)
