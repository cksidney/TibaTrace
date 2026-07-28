from rest_framework.routers import SimpleRouter

from apps.pharmacy_network.api.views import PharmacyViewSet

router = SimpleRouter()
router.register("pharmacies", PharmacyViewSet, basename="pharmacy")
urlpatterns = router.urls
