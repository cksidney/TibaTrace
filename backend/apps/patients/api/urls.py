from rest_framework.routers import SimpleRouter

from apps.patients.api.views import PatientViewSet

router = SimpleRouter()
router.register("", PatientViewSet, basename="patient")
urlpatterns = router.urls
