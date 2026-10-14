"""Inspection only: maintenance UI must never bypass governed business services."""
from functools import wraps

from django.contrib.admin import AdminSite, ModelAdmin
from django.contrib.admin.apps import AdminConfig
from django.core.exceptions import PermissionDenied

from apps.core.tenant_context import get_current_tenant_id


class ReadOnlyMaintenanceAdmin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        return {}

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if any(field.name == "tenant" for field in self.model._meta.fields):
            tenant_id = get_current_tenant_id()
            return queryset.filter(tenant_id=tenant_id) if tenant_id else queryset.none()
        return queryset


class WorkflowAdminSite(AdminSite):
    site_header = "TibaTrace read-only maintenance inspector"
    site_title = "TibaTrace inspection"
    index_title = "Business writes belong in governed HQ/API workflows"

    def has_permission(self, request):
        return super().has_permission(request) and (request.user.is_superuser or request.user.is_platform_admin)

    def register(self, model_or_iterable, admin_class=None, **options):
        original = admin_class or ModelAdmin
        protected = type(f"ReadOnly{original.__name__}", (ReadOnlyMaintenanceAdmin, original), {})
        return super().register(model_or_iterable, protected, **options)

    def admin_view(self, view, cacheable=False):
        authorised = super().admin_view(view, cacheable=cacheable)

        @wraps(authorised)
        def inspect_only(request, *args, **kwargs):
            # Also covers custom ModelAdmin routes and password/change forms,
            # not just model permission hooks. Login is a separate public auth
            # view; authenticated POST logout remains possible.
            if request.method not in {"GET", "HEAD", "OPTIONS"} and view != self.logout:
                raise PermissionDenied("Maintenance inspection is read-only. Use the governed HQ/API workflow.")
            return authorised(request, *args, **kwargs)

        return inspect_only


class GovernedAdminConfig(AdminConfig):
    default_site = "apps.core.admin_site.WorkflowAdminSite"
