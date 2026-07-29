from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PosTransactionViewSet, RetailCatalogueViewSet

router = DefaultRouter()
router.register("transactions", PosTransactionViewSet, basename="pos-transaction")
router.register("catalogue", RetailCatalogueViewSet, basename="pos-retail-catalogue")

urlpatterns = [path("", include(router.urls))]
