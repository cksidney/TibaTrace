from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api.viewsets import TenantModelViewSet
from apps.patients.api.serializers import (
    PatientAllergySerializer,
    PatientClinicalSummarySerializer,
    PatientIdentifierCreateSerializer,
    PatientIdentifierSerializer,
    PatientIdentifierVerificationSerializer,
    PatientMedicationHistorySerializer,
    PatientSerializer,
)
from apps.patients.models import Patient, PatientClinicalSummary, PatientIdentifier
from apps.patients.services import (
    PatientClinicalSummaryService,
    PatientGovernanceService,
)
from apps.prescription.models import PatientMedicationHistory
from apps.tenancy.models import Tenant


class PatientViewSet(TenantModelViewSet):
    queryset = Patient.all_objects.select_related("clinical_summary").prefetch_related(
        "identifiers",
        "allergies",
        "medication_statements",
    )
    serializer_class = PatientSerializer
    read_capability = "patients.read"
    write_capability = "patients.write"
    action_capabilities = {
        "create": ("patients.read", "patients.create"),
        "identifiers": (
            "patients.identity.view",
            "patients.identity.manage",
        ),
        "verify_identifier": (
            "patients.identity.manage",
            "patients.identity.manage",
        ),
        "allergies": (
            "patients.sensitive.view",
            "patients.allergy.record",
        ),
        "medication_history": (
            "patients.sensitive.view",
            "patients.sensitive.view",
        ),
        "clinical_summary": (
            "patients.sensitive.view",
            "patients.clinical_summary.manage",
        ),
    }
    search_fields = (
        "internal_reference_id",
        "patient_number",
        "external_patient_reference",
        "first_name",
        "last_name",
        "phone",
    )

    def get_permissions(self):
        capabilities = self.action_capabilities.get(self.action)
        if capabilities:
            self.read_capability, self.write_capability = capabilities
        return super().get_permissions()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Patient.all_objects.none()
        queryset = Patient.all_objects.filter(
            tenant_id=self.request.tenant_id
        )
        capabilities = getattr(
            self.request,
            "effective_capabilities",
            set(),
        )
        if "*" in capabilities or "patients.sensitive.view" in capabilities:
            queryset = queryset.select_related(
                "clinical_summary"
            ).prefetch_related("allergies", "medication_statements")
        if "*" in capabilities or "patients.identity.view" in capabilities:
            queryset = queryset.prefetch_related("identifiers")
        return queryset

    def perform_create(self, serializer):
        values = dict(serializer.validated_data)
        internal_reference_id = values.pop("internal_reference_id")
        patient_number = values.pop("patient_number", "") or internal_reference_id
        try:
            serializer.instance = PatientGovernanceService.create_patient(
                tenant=Tenant.objects.get(id=self.request.tenant_id),
                actor=self.request.user,
                patient_number=patient_number,
                internal_reference_id=internal_reference_id,
                **values,
            )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages) from exc
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc

    @action(detail=True, methods=["get", "post"])
    def identifiers(self, request, pk=None):
        patient = self.get_object()
        if request.method == "GET":
            serializer = PatientIdentifierSerializer(
                patient.identifiers.all(),
                many=True,
                context=self.get_serializer_context(),
            )
            return Response(serializer.data)
        input_serializer = PatientIdentifierCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            identifier = PatientGovernanceService.add_identifier(
                patient=patient,
                actor=request.user,
                **input_serializer.validated_data,
            )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages) from exc
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc
        return Response(
            PatientIdentifierSerializer(identifier).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"identifiers/(?P<identifier_id>[^/.]+)/verify",
    )
    def verify_identifier(self, request, pk=None, identifier_id=None):
        patient = self.get_object()
        identifier = PatientIdentifier.all_objects.filter(
            tenant_id=request.tenant_id,
            patient=patient,
            pk=identifier_id,
        ).first()
        if identifier is None:
            raise NotFound("Patient identifier was not found in this patient record.")
        serializer = PatientIdentifierVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            identifier = PatientGovernanceService.verify_identifier(
                identifier=identifier,
                actor=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages) from exc
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc
        return Response(PatientIdentifierSerializer(identifier).data)

    @action(detail=True, methods=["get", "post"])
    def allergies(self, request, pk=None):
        patient = self.get_object()
        if request.method == "GET":
            return Response(
                PatientAllergySerializer(
                    patient.allergies.all(),
                    many=True,
                ).data
            )
        serializer = PatientAllergySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allergy = PatientGovernanceService.record_allergy(
            patient=patient,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            PatientAllergySerializer(allergy).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="medication-history")
    def medication_history(self, request, pk=None):
        patient = self.get_object()
        history = PatientMedicationHistory.all_objects.filter(
            tenant_id=request.tenant_id,
            patient=patient,
        ).order_by("-supplied_at")
        return Response(
            PatientMedicationHistorySerializer(history, many=True).data
        )

    @action(detail=True, methods=["get", "put"], url_path="clinical-summary")
    def clinical_summary(self, request, pk=None):
        patient = self.get_object()
        if request.method == "GET":
            summary = PatientClinicalSummary.all_objects.filter(
                tenant_id=request.tenant_id,
                patient=patient,
            ).first()
            if not summary:
                return Response(status=status.HTTP_204_NO_CONTENT)
            return Response(PatientClinicalSummarySerializer(summary).data)
        serializer = PatientClinicalSummarySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        summary = PatientClinicalSummaryService.update_summary(
            patient=patient,
            actor=request.user,
            source=values.pop("source", "NOT_RECORDED"),
            verification_status=values.pop("verification_status", "UNVERIFIED"),
            **values,
        )
        return Response(PatientClinicalSummarySerializer(summary).data)
