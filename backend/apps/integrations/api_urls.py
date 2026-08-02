"""National Integration Foundation (NIF) API URL routing.

Tenant surfaces:
  /api/nif/premises-verifications/          GET (list own)
  /api/nif/premises-verifications/submit/   POST (submit evidence)
  /api/nif/notifications/                    GET notifications

Platform Owner surfaces:
  /api/nif/platform/premises-verifications/              GET list all
  /api/nif/platform/providers/                       CRUD
  /api/nif/platform/activations/                     CRUD
  /api/nif/platform/dead-letters/                    GET all DLQ
  /api/nif/platform/recalls/                         CRUD alerts
  /api/nif/platform/notifications/                   GET all notifications
  /api/nif/platform/role-preferences/               CRUD role notification preferences
  /api/nif/platform/regulatory-expiries/             CRUD & evaluate regulatory expiries
  /api/nif/platform/reports/                         GET compliance reports (CSV, Excel, PDF, JSON)
  /api/nif/platform/evidence/                        GET certification evidence package (JSON, ZIP)
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
from apps.notifications.views import (
    IntegrationNotificationViewSet,
    NotificationRolePreferenceViewSet,
    RegulatoryExpiryTrackViewSet,
)
from apps.pharmacy_network.views_nif import (
    PlatformPremisesVerificationViewSet,
    TenantPremisesVerificationSubmitView,
    TenantPremisesVerificationView,
)
from apps.platform.reporting.views import (
    CertificationEvidenceView,
    ComplianceReportView,
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
platform_router.register(
    r"notifications",
    IntegrationNotificationViewSet,
    basename="platform-notification",
)
platform_router.register(
    r"role-preferences",
    NotificationRolePreferenceViewSet,
    basename="platform-role-preference",
)
platform_router.register(
    r"regulatory-expiries",
    RegulatoryExpiryTrackViewSet,
    basename="platform-regulatory-expiry",
)

# Tenant router
tenant_router = DefaultRouter()
tenant_router.register(
    r"impacts",
    TenantRegulatoryImpactViewSet,
    basename="tenant-regulatory-impact",
)
tenant_router.register(
    r"notifications",
    IntegrationNotificationViewSet,
    basename="tenant-notification",
)

urlpatterns = [
    # Tenant surfaces
    path("premises-verifications/", TenantPremisesVerificationView.as_view(), name="tenant-premises-list"),
    path("premises-verifications/submit/", TenantPremisesVerificationSubmitView.as_view(), name="tenant-premises-submit"),
    path("recalls/", include(tenant_router.urls)),
    path("notifications/", include(tenant_router.urls)),

    # Platform Owner & Compliance surfaces
    path("platform/reports/", ComplianceReportView.as_view(), name="platform-compliance-reports"),
    path("platform/evidence/", CertificationEvidenceView.as_view(), name="platform-certification-evidence"),
    path("platform/", include(platform_router.urls)),
]
