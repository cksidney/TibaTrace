"""National Integration Foundation (NIF) API URL routing.

Tenant surfaces:
  /api/nif/premises-verifications/          GET (list own)
  /api/nif/premises-verifications/submit/   POST (submit evidence)

Platform Owner surfaces:
  /api/nif/platform/premises-verifications/              GET list all
  /api/nif/platform/premises-verifications/{id}/         GET detail
  /api/nif/platform/premises-verifications/{id}/review/  POST approve/reject/clarify
  /api/nif/platform/premises-verifications/{id}/snapshots/ GET audit trail

  /api/nif/platform/providers/                       CRUD
  /api/nif/platform/providers/{id}/health/           GET health history
  /api/nif/platform/providers/{id}/messages/         GET message queue
  /api/nif/platform/providers/{id}/dead-letters/     GET DLQ

  /api/nif/platform/activations/                     CRUD
  /api/nif/platform/activations/{id}/advance/        POST advance state

  /api/nif/platform/dead-letters/                    GET all DLQ
  /api/nif/platform/dead-letters/{id}/replay/        POST replay

  /api/nif/platform/recalls/                         CRUD alerts
  /api/nif/platform/recalls/{id}/activate/           POST activate
  /api/nif/platform/recalls/{id}/versions/           GET versions
  /api/nif/platform/recalls/{id}/impacts/            GET all impacts
  /api/nif/platform/recalls/{id}/quarantine/         POST quarantine tenant

  /api/nif/recalls/impacts/                          GET tenant impacts (tenant-scoped)
  /api/nif/recalls/impacts/{id}/actions/             POST add action
  /api/nif/recalls/impacts/{id}/close/               POST close with evidence
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.integrations.views import (
    DeadLetterReplayView,
    ProviderActivationRequestViewSet,
    ProviderConfigurationViewSet,
)
from apps.inventory.recalls.views import (
    PlatformRegulatoryAlertViewSet,
    TenantRegulatoryImpactViewSet,
)
from apps.pharmacy_network.views_nif import (
    PlatformPremisesVerificationViewSet,
    TenantPremisesVerificationSubmitView,
    TenantPremisesVerificationView,
)

# Platform Owner router
platform_router = DefaultRouter()
platform_router.register(
    r"premises-verifications",
    PlatformPremisesVerificationViewSet,
    basename="platform-premises-verification",
)
platform_router.register(
    r"providers",
    ProviderConfigurationViewSet,
    basename="platform-provider-configuration",
)
platform_router.register(
    r"activations",
    ProviderActivationRequestViewSet,
    basename="platform-activation-request",
)
platform_router.register(
    r"dead-letters",
    DeadLetterReplayView,
    basename="platform-dead-letter",
)
platform_router.register(
    r"recalls",
    PlatformRegulatoryAlertViewSet,
    basename="platform-regulatory-alert",
)

# Tenant router
tenant_router = DefaultRouter()
tenant_router.register(
    r"impacts",
    TenantRegulatoryImpactViewSet,
    basename="tenant-regulatory-impact",
)

urlpatterns = [
    # Tenant surfaces
    path("premises-verifications/", TenantPremisesVerificationView.as_view(), name="tenant-premises-list"),
    path("premises-verifications/submit/", TenantPremisesVerificationSubmitView.as_view(), name="tenant-premises-submit"),
    path("recalls/", include(tenant_router.urls)),

    # Platform Owner surfaces
    path("platform/", include(platform_router.urls)),
]
