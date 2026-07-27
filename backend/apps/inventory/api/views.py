from rest_framework import permissions, viewsets

from apps.core.tenant_context import get_current_tenant_id
from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
)

from .serializers import (
    InventoryBalanceSerializer,
    InventoryBatchSerializer,
    InventoryLedgerEntrySerializer,
    InventoryLocationSerializer,
    InventoryReservationSerializer,
)


class TenantScopedQuerysetMixin:
    """Build the queryset per request, from the model, with an explicit filter.

    These viewsets declared `queryset = Model.objects.all()` as a class
    attribute. `objects` is the tenant-strict manager and a class attribute is
    evaluated once at import, when there is definitively no tenant context, so
    it returned `.none()`. DRF clones that queryset per request rather than
    re-consulting the manager, so it stayed empty for the life of the process --
    every inventory endpoint returned nothing, for every caller.

    Same shape as the fix in apps/medicines/api/views.py. The isolation is now
    an explicit filter on a line you can read, rather than a thread-local set by
    middleware that happens to run earlier.
    """

    model = None
    select_related: list[str] = []

    def tenant_id(self):
        request = self.request
        return (
            get_current_tenant_id()
            or getattr(request, "tenant_id", None)
            or getattr(request.user, "tenant_id", None)
        )

    def get_queryset(self):
        tenant_id = self.tenant_id()
        if tenant_id is None:
            # No tenant, no rows. Stock levels and ledger entries belong to one
            # pharmacy; an unscoped read here would expose another's.
            return self.model.all_objects.none()
        queryset = self.model.all_objects.filter(tenant_id=tenant_id)
        if self.select_related:
            queryset = queryset.select_related(*self.select_related)
        return queryset


class InventoryLocationViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory locations.
    """
    model = InventoryLocation
    select_related = ['branch']
    serializer_class = InventoryLocationSerializer
    permission_classes = [permissions.IsAuthenticated]

class InventoryBatchViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory batches.
    """
    model = InventoryBatch
    select_related = ['sku', 'manufactured_product']
    serializer_class = InventoryBatchSerializer
    permission_classes = [permissions.IsAuthenticated]

class InventoryLedgerEntryViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing the append-only inventory ledger.
    """
    model = InventoryLedgerEntry
    select_related = ['sku', 'location', 'inventory_batch']
    serializer_class = InventoryLedgerEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

class InventoryBalanceViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory balances.
    """
    model = InventoryBalance
    select_related = ['sku', 'location']
    serializer_class = InventoryBalanceSerializer
    permission_classes = [permissions.IsAuthenticated]

class InventoryReservationViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory reservations.
    """
    model = InventoryReservation
    select_related = ['sku', 'location']
    serializer_class = InventoryReservationSerializer
    permission_classes = [permissions.IsAuthenticated]
