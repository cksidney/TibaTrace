from rest_framework.routers import DefaultRouter

from apps.customers.api.views import CustomerCommercialProfileViewSet, CustomerDeliveryAddressViewSet, CustomerViewSet

router = DefaultRouter()
router.register(r"customers", CustomerViewSet, basename="customer")
router.register(r"customer-addresses", CustomerDeliveryAddressViewSet, basename="customer-address")
router.register(r"customer-profiles", CustomerCommercialProfileViewSet, basename="customer-profile")

urlpatterns = router.urls
