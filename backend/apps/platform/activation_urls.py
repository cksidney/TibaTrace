from rest_framework.routers import DefaultRouter

from .activation_views import PlatformPosActivationViewSet, TenantPosActivationViewSet

router = DefaultRouter()
router.register("platform/pos-activations/requests", PlatformPosActivationViewSet, basename="platform-pos-activation")
router.register("tenant/pos-activations/requests", TenantPosActivationViewSet, basename="tenant-pos-activation")
urlpatterns = router.urls
