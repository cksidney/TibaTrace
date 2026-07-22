from rest_framework.routers import DefaultRouter

from apps.procurement.api.views import (
    GoodsReceiptViewSet,
    PurchaseOrderViewSet,
    PurchaseRequisitionViewSet,
    ReceivedBatchViewSet,
    ReceivingInspectionViewSet,
    SupplierProductAgreementViewSet,
    SupplierQualificationViewSet,
    SupplierReturnViewSet,
    SupplierViewSet,
    ThreeWayMatchViewSet,
)

router = DefaultRouter()
router.register(r"suppliers", SupplierViewSet, basename="supplier")
router.register(r"supplier-qualifications", SupplierQualificationViewSet, basename="supplier-qualification")
router.register(r"supplier-products", SupplierProductAgreementViewSet, basename="supplier-product")
router.register(r"requisitions", PurchaseRequisitionViewSet, basename="purchase-requisition")
router.register(r"purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register(r"goods-receipts", GoodsReceiptViewSet, basename="goods-receipt")
router.register(r"received-batches", ReceivedBatchViewSet, basename="received-batch")
router.register(r"inspections", ReceivingInspectionViewSet, basename="receiving-inspection")
router.register(r"supplier-returns", SupplierReturnViewSet, basename="supplier-return")
router.register(r"matching", ThreeWayMatchViewSet, basename="three-way-match")

urlpatterns = router.urls
