from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.prescription.checkout_api import mpesa_callback
from apps.prescription.payment_api.views import (
    PaymentIntentViewSet,
    PaymentSettlementViewSet,
    PaymentTenderViewSet,
)

router = DefaultRouter()
router.register("intents", PaymentIntentViewSet, basename="pos-payment-intents")
router.register("tenders", PaymentTenderViewSet, basename="pos-payment-tenders")
router.register("settlements", PaymentSettlementViewSet, basename="pos-payment-settlements")

urlpatterns = [path("mpesa/callback/", mpesa_callback, name="checkout-mpesa-callback")] + router.urls
