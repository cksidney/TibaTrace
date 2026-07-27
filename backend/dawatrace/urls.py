from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.platform.admin_shell import admin_shell
from apps.platform.release_views import PosReleaseDownloadView, PosReleaseListView
from apps.platform.views import (
    HQOverviewView,
    HQWorkspaceView,
    PlatformInfoView,
    health,
    pos_terminal_view,
)

urlpatterns = [
    path("", pos_terminal_view, name="pos-home"),
    path("pos/", pos_terminal_view, name="pos-terminal"),
    path("admin/", admin.site.urls),
    path("admin-shell/", admin_shell, name="admin-shell"),
    path("api/health/", health, name="health"),
    path("api/platform/", PlatformInfoView.as_view(), name="platform-info"),
    path("api/hq/overview/", HQOverviewView.as_view(), name="hq-overview"),
    path("api/hq/workspace/", HQWorkspaceView.as_view(), name="hq-workspace"),
    path("api/hq/pos-releases/", PosReleaseListView.as_view(), name="pos-release-list"),
    path(
        "api/hq/pos-releases/<uuid:pk>/download/",
        PosReleaseDownloadView.as_view(),
        name="pos-release-download",
    ),
    path("api/tenancy/", include("apps.tenancy.api.urls")),
    path("api/identity/", include("apps.identity.api.urls")),
    path("api/organizations/", include("apps.organizations.api.urls")),
    path("api/patients/", include("apps.patients.api.urls")),
    path("api/practitioners/", include("apps.practitioners.api.urls")),
    path("api/prescribers/", include("apps.practitioners.api.urls")),
    path("api/", include("apps.prescription.api.urls")),
    path("api/clinical/", include("apps.clinical.urls")),
    path("api/cds/", include("apps.cds.urls")),
    path("api/pos/clinical-screening/", include("apps.cds.pos_api.urls")),
    path("api/pos/dispensing/", include("apps.prescription.pos_dispensing_api.urls")),
    path("api/pos/payments/", include("apps.prescription.payment_api.urls")),
    path("api/terminology/", include("apps.terminology.urls")),
    path("api/audit/", include("apps.audit.urls")),
    path("api/documents/", include("apps.documents.urls")),
    path("api/medicines/", include("apps.medicines.api.urls")),
    path("api/procurement/", include("apps.procurement.api.urls")),
    path("api/inventory/", include("apps.inventory.api.urls")),
    path("api/insurance/", include("apps.insurance.api.urls")),
    path("api/pricing/", include("apps.pricing.api.urls")),
    path("api/pos/shift/", include("apps.pos_shift.api.urls")),
    path("api/fhir/r4/", include("apps.fhir.urls")),
    path("api/customers/", include("apps.customers.api.urls")),
    path("api/sales/", include("apps.sales.api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
