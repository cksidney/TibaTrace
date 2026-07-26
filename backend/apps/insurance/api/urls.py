from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ClaimRejectionViewSet,
    ClaimViewSet,
    CoverageVerificationViewSet,
    CoverageViewSet,
    InsurerViewSet,
    RemittanceViewSet,
)

router = DefaultRouter()
router.register("insurers", InsurerViewSet, basename="insurance-insurer")
router.register("coverages", CoverageViewSet, basename="insurance-coverage")
router.register("verifications", CoverageVerificationViewSet, basename="insurance-verification")
router.register("claims", ClaimViewSet, basename="insurance-claim")
router.register("rejections", ClaimRejectionViewSet, basename="insurance-rejection")
router.register("remittances", RemittanceViewSet, basename="insurance-remittance")

urlpatterns = [path("", include(router.urls))]
