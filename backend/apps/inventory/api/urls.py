from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .operations import InventoryChangeViewSet
from .planning import BarcodeViewSet, PolicyViewSet, RecommendationViewSet, WarehouseTaskViewSet
from .views import (
    InventoryBalanceViewSet,
    InventoryBatchViewSet,
    InventoryLedgerEntryViewSet,
    InventoryLocationViewSet,
    InventoryReservationViewSet,
    StocktakeViewSet,
    StockTransferViewSet,
)

router = DefaultRouter()
router.register(r"barcode-packs", BarcodeViewSet, basename="barcode-pack")
router.register(r"replenishment-policies", PolicyViewSet, basename="replenishment-policy")
router.register(r"replenishment", RecommendationViewSet, basename="replenishment")
router.register(r"warehouse-tasks", WarehouseTaskViewSet, basename="warehouse-task")
router.register(r"changes", InventoryChangeViewSet, basename="inventory-change")
router.register(r"locations", InventoryLocationViewSet, basename="inventory-location")
router.register(r"batches", InventoryBatchViewSet, basename="inventory-batch")
router.register(r"ledger", InventoryLedgerEntryViewSet, basename="inventory-ledger")
router.register(r"balances", InventoryBalanceViewSet, basename="inventory-balance")
router.register(r"reservations", InventoryReservationViewSet, basename="inventory-reservation")
router.register(r"transfers", StockTransferViewSet, basename="stock-transfer")
router.register(r"stocktakes", StocktakeViewSet, basename="stocktake")

urlpatterns = [
    path("", include(router.urls)),
]
