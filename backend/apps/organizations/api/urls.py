from rest_framework.routers import SimpleRouter

from apps.organizations.api.views import LocationViewSet, OrganizationViewSet

router = SimpleRouter()
router.register("locations", LocationViewSet, basename="location")
router.register("", OrganizationViewSet, basename="organization")
urlpatterns = router.urls
