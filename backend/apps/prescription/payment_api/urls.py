from rest_framework.routers import DefaultRouter

from apps.prescription.payment_api.views import (
    PaymentIntentViewSet,
    PaymentSettlementViewSet,
    PaymentTenderViewSet,
)

router = DefaultRouter()
router.register("intents", PaymentIntentViewSet, basename="pos-payment-intents")
router.register("tenders", PaymentTenderViewSet, basename="pos-payment-tenders")
router.register("settlements", PaymentSettlementViewSet, basename="pos-payment-settlements")

urlpatterns = router.urls
