from rest_framework.routers import SimpleRouter

from apps.clinical.api import (
    ClinicalDocumentViewSet,
    ConditionViewSet,
    DiagnosticReportViewSet,
    EncounterViewSet,
    MedicationAdministrationViewSet,
    ObservationViewSet,
)

router = SimpleRouter()
router.register("encounters", EncounterViewSet, basename="clinical-encounter")
router.register("conditions", ConditionViewSet, basename="clinical-condition")
router.register("observations", ObservationViewSet, basename="clinical-observation")
router.register("diagnostic-reports", DiagnosticReportViewSet, basename="clinical-report")
router.register("documents", ClinicalDocumentViewSet, basename="clinical-document")
router.register("medication-administrations", MedicationAdministrationViewSet, basename="medication-administration")
urlpatterns = router.urls
