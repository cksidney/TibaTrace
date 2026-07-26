from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AppliedPriceViewSet,
    ManualPriceOverrideViewSet,
    PriceAssignmentViewSet,
    PriceBookEntryViewSet,
    PriceBookVersionViewSet,
    PriceBookViewSet,
    PriceLockViewSet,
    PriceResolutionViewSet,
)

router = DefaultRouter()
router.register("books", PriceBookViewSet, basename="pricing-book")
router.register("versions", PriceBookVersionViewSet, basename="pricing-version")
router.register("entries", PriceBookEntryViewSet, basename="pricing-entry")
router.register("assignments", PriceAssignmentViewSet, basename="pricing-assignment")
router.register("applied", AppliedPriceViewSet, basename="pricing-applied")
router.register("overrides", ManualPriceOverrideViewSet, basename="pricing-override")
router.register("locks", PriceLockViewSet, basename="pricing-lock")
router.register("prices", PriceResolutionViewSet, basename="pricing-resolve")

urlpatterns = [path("", include(router.urls))]
