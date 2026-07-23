from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.platform.admin_shell import admin_shell
from apps.platform.views import PlatformInfoView, health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("admin-shell/", admin_shell, name="admin-shell"),
    path("api/health/", health, name="health"),
    path("api/platform/", PlatformInfoView.as_view(), name="platform-info"),
    path("api/identity/", include("apps.identity.api.urls")),
    path("api/organizations/", include("apps.organizations.api.urls")),
    path("api/patients/", include("apps.patients.api.urls")),
    path("api/practitioners/", include("apps.practitioners.api.urls")),
    path("api/", include("apps.prescription.api.urls")),
    path("api/clinical/", include("apps.clinical.urls")),
    path("api/cds/", include("apps.cds.urls")),
    path("api/terminology/", include("apps.terminology.urls")),
    path("api/audit/", include("apps.audit.urls")),
    path("api/documents/", include("apps.documents.urls")),
    path("api/medicines/", include("apps.medicines.api.urls")),
    path("api/procurement/", include("apps.procurement.api.urls")),
    path("api/inventory/", include("apps.inventory.api.urls")),
    path("api/fhir/r4/", include("apps.fhir.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
