from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.clinical.models import (
    ClinicalCondition,
    ClinicalDiagnosticReport,
    ClinicalDocument,
    ClinicalEncounter,
    ClinicalObservation,
    MedicationAdministrationRecord,
)
from apps.core.permissions import TenantCapabilityPermission


def _serializer(model):
    class Serializer(serializers.ModelSerializer):
        class Meta:
            fields = "__all__"

    Serializer.Meta.model = model
    Serializer.__name__ = f"{model.__name__}Serializer"
    Serializer.__qualname__ = Serializer.__name__
    return Serializer


class TenantClinicalReadViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "clinical.read"
    write_capability = "clinical.write"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset.model.all_objects.none()
        return self.queryset.model.all_objects.filter(tenant_id=self.request.tenant_id)


class EncounterViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalEncounter.all_objects.all()
    serializer_class = _serializer(ClinicalEncounter)


class ConditionViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalCondition.all_objects.all()
    serializer_class = _serializer(ClinicalCondition)


class ObservationViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalObservation.all_objects.all()
    serializer_class = _serializer(ClinicalObservation)


class DiagnosticReportViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalDiagnosticReport.all_objects.all()
    serializer_class = _serializer(ClinicalDiagnosticReport)


class ClinicalDocumentViewSet(TenantClinicalReadViewSet):
    queryset = ClinicalDocument.all_objects.all()
    serializer_class = _serializer(ClinicalDocument)


class MedicationAdministrationViewSet(TenantClinicalReadViewSet):
    queryset = MedicationAdministrationRecord.all_objects.all()
    serializer_class = _serializer(MedicationAdministrationRecord)
