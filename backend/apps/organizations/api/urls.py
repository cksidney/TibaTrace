from rest_framework.routers import SimpleRouter

from apps.organizations.api.views import LocationViewSet, OrganizationViewSet

router = SimpleRouter()
router.register("", OrganizationViewSet, basename="organization")
router.register("locations", LocationViewSet, basename="location")
urlpatterns = router.urls
