from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.service import log_audit
from apps.clinical.models import (
    ClinicalCondition,
    ClinicalDiagnosticReport,
    ClinicalDocument,
    ClinicalEncounter,
    ClinicalObservation,
    MedicationAdministrationRecord,
)
from apps.core.permissions import TenantCapabilityPermission
from apps.fhir.exceptions import FHIRException, FHIRSecurityError
from apps.workflows.service import emit_event


def _serializer(model):
    class Serializer(serializers.ModelSerializer):
        class Meta:
            fields = "__all__"

    Serializer.Meta.model = model
    Serializer.__name__ = f"{model.__name__}Serializer"
    Serializer.__qualname__ = Serializer.__name__
    return Serializer


class EncounterIntakeSerializer(serializers.Serializer):
    ENCOUNTER_CLASSES = tuple(
        (value, value)
        for value in ("AMB", "EMER", "FLD", "HH", "IMP", "OBSENC", "PRENC", "SS", "VR")
    )

    patient_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=ClinicalEncounter.STATUS_CHOICES, default="IN_PROGRESS")
    encounter_class = serializers.ChoiceField(choices=ENCOUNTER_CLASSES)
    start_time = serializers.DateTimeField(required=False, allow_null=True)
    end_time = serializers.DateTimeField(required=False, allow_null=True)
    reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)
    organization_id = serializers.UUIDField(required=False, allow_null=True)
    practitioner_id = serializers.UUIDField(required=False, allow_null=True)


class ConditionIntakeSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    encounter_id = serializers.UUIDField(required=False, allow_null=True)
    clinical_status = serializers.ChoiceField(choices=ClinicalCondition.STATUS_CHOICES, default="ACTIVE")
    verification_status = serializers.ChoiceField(
        choices=ClinicalCondition.VERIFICATION_CHOICES,
        default="UNCONFIRMED",
    )
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)
    code = serializers.CharField(max_length=100)
    system = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    display = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    onset_date = serializers.DateTimeField(required=False, allow_null=True)


class ObservationIntakeSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    encounter_id = serializers.UUIDField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=ClinicalObservation.STATUS_CHOICES, default="FINAL")
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)
    code = serializers.CharField(max_length=100)
    system = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    display = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    effective_time = serializers.DateTimeField(required=False, allow_null=True)
    value_quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=4,
        required=False,
        allow_null=True,
    )
    value_unit = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=50)
    value_string = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    interpretation = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=50)


class TenantClinicalReadViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "clinical.read"
    write_capability = "clinical.write"
    intake_serializer_class = None
    intake_service_method = ""
    intake_resource_type = ""

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset.model.all_objects.none()
        return self.queryset.model.all_objects.filter(tenant_id=self.request.tenant_id)

    def create(self, request, *args, **kwargs):
        serializer_class = self.intake_serializer_class
        if serializer_class is None or not self.intake_service_method:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

        intake = serializer_class(data=request.data)
        intake.is_valid(raise_exception=True)
        from apps.clinical.services import ClinicalDomainService

        tenant_id = request.tenant_id
        try:
            with transaction.atomic():
                record = getattr(ClinicalDomainService, self.intake_service_method)(
                    intake.validated_data,
                    tenant_id,
                )
                log_audit(
                    tenant_id=tenant_id,
                    action="CLINICAL_RECORD_INGESTED",
                    model_name=self.intake_resource_type,
                    object_id=record.pk,
                    actor_id=request.user.pk,
                    metadata={
                        "resource_type": self.intake_resource_type,
                        "patient_id": str(record.patient_id),
                        "source": "HQ_WORKSPACE",
                    },
                )
                emit_event(
                    tenant_id=tenant_id,
                    aggregate_type=self.intake_resource_type,
                    aggregate_id=record.pk,
                    event_type=f"clinical.{self.intake_resource_type.lower()}.created",
                    payload={
                        "resource_type": self.intake_resource_type,
                        "resource_id": str(record.pk),
                    },
                    auto_process=False,
                )
        except FHIRSecurityError as exc:
            raise PermissionDenied(exc.message) from exc
        except FHIRException as exc:
            raise serializers.ValidationError({"detail": exc.message}) from exc

        return Response(self.get_serializer(record).data, status=status.HTTP_201_CREATED)


class EncounterViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalEncounter.all_objects.all()
    serializer_class = _serializer(ClinicalEncounter)
    intake_serializer_class = EncounterIntakeSerializer
    intake_service_method = "process_encounter"
    intake_resource_type = "Encounter"


class ConditionViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalCondition.all_objects.all()
    serializer_class = _serializer(ClinicalCondition)
    intake_serializer_class = ConditionIntakeSerializer
    intake_service_method = "process_condition"
    intake_resource_type = "Condition"


class ObservationViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalObservation.all_objects.all()
    serializer_class = _serializer(ClinicalObservation)
    intake_serializer_class = ObservationIntakeSerializer
    intake_service_method = "process_observation"
    intake_resource_type = "Observation"


class DiagnosticReportViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalDiagnosticReport.all_objects.all()
    serializer_class = _serializer(ClinicalDiagnosticReport)


class ClinicalDocumentViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalDocument.all_objects.all()
    serializer_class = _serializer(ClinicalDocument)


class MedicationAdministrationViewSet(TenantClinicalReadViewSet):
    queryset = MedicationAdministrationRecord.all_objects.all()
    serializer_class = _serializer(MedicationAdministrationRecord)
