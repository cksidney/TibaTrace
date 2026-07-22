from rest_framework.routers import SimpleRouter

from apps.practitioners.api.views import PractitionerViewSet

router = SimpleRouter()
router.register("", PractitionerViewSet, basename="practitioner")
urlpatterns = router.urls
