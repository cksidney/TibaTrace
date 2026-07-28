from rest_framework.routers import DefaultRouter

from apps.prescription.pos_dispensing_api.views import (
    PosDeviceHealthViewSet,
    PosDispensingViewSet,
    PosPrintJobViewSet,
    PosShiftViewSet,
)

router = DefaultRouter()
router.register("episodes", PosDispensingViewSet, basename="pos-dispensing-episodes")
router.register("shifts", PosShiftViewSet, basename="pos-dispensing-shifts")
router.register("devices", PosDeviceHealthViewSet, basename="pos-dispensing-devices")
router.register("print-jobs", PosPrintJobViewSet, basename="pos-dispensing-print-jobs")

urlpatterns = router.urls
