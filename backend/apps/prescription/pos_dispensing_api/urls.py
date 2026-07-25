from rest_framework.routers import DefaultRouter

from apps.prescription.pos_dispensing_api.views import (
    PosDeviceHealthViewSet,
    PosDispensingViewSet,
    PosShiftViewSet,
)

router = DefaultRouter()
router.register("episodes", PosDispensingViewSet, basename="pos-dispensing-episodes")
router.register("shifts", PosShiftViewSet, basename="pos-dispensing-shifts")
router.register("devices", PosDeviceHealthViewSet, basename="pos-dispensing-devices")

urlpatterns = router.urls
