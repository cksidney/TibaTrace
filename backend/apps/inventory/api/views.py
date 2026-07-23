from rest_framework import permissions, viewsets

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


class InventoryLocationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory locations.
    """
    queryset = InventoryLocation.objects.all()
    serializer_class = InventoryLocationSerializer
    permission_classes = [permissions.IsAuthenticated]

class InventoryBatchViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory batches.
    """
    queryset = InventoryBatch.objects.all()
    serializer_class = InventoryBatchSerializer
    permission_classes = [permissions.IsAuthenticated]

class InventoryLedgerEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing the append-only inventory ledger.
    """
    queryset = InventoryLedgerEntry.objects.all()
    serializer_class = InventoryLedgerEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

class InventoryBalanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory balances.
    """
    queryset = InventoryBalance.objects.all()
    serializer_class = InventoryBalanceSerializer
    permission_classes = [permissions.IsAuthenticated]

class InventoryReservationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory reservations.
    """
    queryset = InventoryReservation.objects.all()
    serializer_class = InventoryReservationSerializer
    permission_classes = [permissions.IsAuthenticated]
