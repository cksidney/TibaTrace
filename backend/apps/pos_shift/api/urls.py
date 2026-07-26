from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BusinessDayViewSet,
    CashDeclarationViewSet,
    CashMovementViewSet,
    OperatorShiftViewSet,
    PosRegisterViewSet,
    RegisterSessionViewSet,
    ShiftReportReprintViewSet,
    ShiftReportViewSet,
)

router = DefaultRouter()
router.register("registers", PosRegisterViewSet, basename="shift-register")
router.register("business-days", BusinessDayViewSet, basename="shift-business-day")
router.register("sessions", RegisterSessionViewSet, basename="shift-session")
router.register("shifts", OperatorShiftViewSet, basename="shift-operator-shift")
router.register("cash-declarations", CashDeclarationViewSet, basename="shift-declaration")
router.register("cash-movements", CashMovementViewSet, basename="shift-movement")
router.register("reports", ShiftReportViewSet, basename="shift-report")
router.register("reprints", ShiftReportReprintViewSet, basename="shift-reprint")

urlpatterns = [path("", include(router.urls))]
