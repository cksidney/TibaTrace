from rest_framework.routers import SimpleRouter

from apps.prescription.api.views import (
    ClinicalWorkItemViewSet,
    DispensingEpisodeViewSet,
    DispensingViewSet,
    PatientReturnViewSet,
    PrescriptionViewSet,
)

router = SimpleRouter()
router.register(
    "clinical/work-items",
    ClinicalWorkItemViewSet,
    basename="clinical-work-item",
)
router.register("prescriptions", PrescriptionViewSet, basename="prescription")
router.register(
    "dispensing/episodes",
    DispensingEpisodeViewSet,
    basename="dispensing-episode",
)
router.register(
    "dispensing/returns",
    PatientReturnViewSet,
    basename="dispensing-return",
)
router.register("dispensing", DispensingViewSet, basename="dispensing")
urlpatterns = router.urls
