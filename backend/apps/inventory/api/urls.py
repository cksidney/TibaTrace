from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    InventoryBalanceViewSet,
    InventoryBatchViewSet,
    InventoryLedgerEntryViewSet,
    InventoryLocationViewSet,
    InventoryReservationViewSet,
    StockTransferViewSet,
)

router = DefaultRouter()
router.register(r"locations", InventoryLocationViewSet, basename="inventory-location")
router.register(r"batches", InventoryBatchViewSet, basename="inventory-batch")
router.register(r"ledger", InventoryLedgerEntryViewSet, basename="inventory-ledger")
router.register(r"balances", InventoryBalanceViewSet, basename="inventory-balance")
router.register(r"reservations", InventoryReservationViewSet, basename="inventory-reservation")
router.register(r"transfers", StockTransferViewSet, basename="stock-transfer")

urlpatterns = [
    path("", include(router.urls)),
]
