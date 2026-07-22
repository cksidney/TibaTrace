from rest_framework.routers import SimpleRouter

from apps.prescription.api.views import DispensingViewSet, PrescriptionViewSet

router = SimpleRouter()
router.register("prescriptions", PrescriptionViewSet, basename="prescription")
router.register("dispensing", DispensingViewSet, basename="dispensing")
urlpatterns = router.urls
