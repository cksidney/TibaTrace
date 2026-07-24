from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.sales.api.views import (
    CustomerPriceAgreementViewSet,
    DeliveryRecordViewSet,
    DispatchOrderViewSet,
    PackageViewSet,
    PackingSessionViewSet,
    PickingTaskViewSet,
    PickingWaveViewSet,
    PriceListEntryViewSet,
    PriceListViewSet,
    PromotionRuleViewSet,
    QuotationViewSet,
    SalesOrderAllocationViewSet,
    SalesOrderHoldViewSet,
    SalesOrderViewSet,
    SalesReturnAuthorizationViewSet,
)

router = DefaultRouter()
router.register(r"price-lists", PriceListViewSet, basename="price-list")
router.register(r"price-entries", PriceListEntryViewSet, basename="price-entry")
router.register(r"price-agreements", CustomerPriceAgreementViewSet, basename="price-agreement")
router.register(r"promotions", PromotionRuleViewSet, basename="promotion")
router.register(r"quotations", QuotationViewSet, basename="quotation")
router.register(r"orders", SalesOrderViewSet, basename="sales-order")
router.register(r"order-holds", SalesOrderHoldViewSet, basename="order-hold")
router.register(r"allocations", SalesOrderAllocationViewSet, basename="allocation")
router.register(r"picking-waves", PickingWaveViewSet, basename="picking-wave")
router.register(r"picking-tasks", PickingTaskViewSet, basename="picking-task")
router.register(r"packing-sessions", PackingSessionViewSet, basename="packing-session")
router.register(r"packages", PackageViewSet, basename="package")
router.register(r"dispatches", DispatchOrderViewSet, basename="dispatch")
router.register(r"deliveries", DeliveryRecordViewSet, basename="delivery")
router.register(r"returns", SalesReturnAuthorizationViewSet, basename="return")

urlpatterns = [
    path("", include(router.urls)),
]
