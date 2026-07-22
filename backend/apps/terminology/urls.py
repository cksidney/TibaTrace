from rest_framework.routers import SimpleRouter

from apps.terminology.api import CodeSystemViewSet, ValueSetViewSet

router = SimpleRouter()
router.register("code-systems", CodeSystemViewSet, basename="terminology-code-system")
router.register("value-sets", ValueSetViewSet, basename="terminology-value-set")
urlpatterns = router.urls
