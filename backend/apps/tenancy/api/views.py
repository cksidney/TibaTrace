from rest_framework import permissions, viewsets

from apps.tenancy.api.serializers import TenantSerializer
from apps.tenancy.models import Tenant


class TenantViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.is_platform_admin:
            return Tenant.objects.all().order_by("name", "id")
        if user.tenant_id:
            return Tenant.objects.filter(pk=user.tenant_id)
        return Tenant.objects.none()

    # The write surface that used to live here is gone.
    #
    # It created a tenant straight into ACTIVE and let a generic PATCH change
    # any field, with no licence check, no actor and no record. A pharmacy could
    # be made live in one POST with no premises licence, no superintendent, no
    # organization and no branch -- and suspending it afterwards stopped nothing.
    #
    # Administration now lives in apps.pharmacy_network, where every transition
    # is guarded and recorded. This viewset stays read-only so that tenancy
    # remains what it is: the scoping infrastructure every request touches.
