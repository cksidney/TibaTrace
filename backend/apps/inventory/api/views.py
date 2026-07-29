from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
    StockTransfer,
)
from apps.inventory.services import StockTransferService
from apps.medicines.models import CommercialSKU
from apps.tenancy.models import Tenant

from .serializers import (
    InventoryBalanceSerializer,
    InventoryBatchSerializer,
    InventoryLedgerEntrySerializer,
    InventoryLocationSerializer,
    InventoryReservationSerializer,
    StockTransferCreateSerializer,
    StockTransferReceiveSerializer,
    StockTransferSerializer,
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
    select_related = ['sku', 'source_location', 'batch']
    serializer_class = InventoryReservationSerializer
    permission_classes = [permissions.IsAuthenticated]


class StockTransferViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = StockTransfer
    select_related = [
        "source_branch",
        "destination_branch",
        "source_location",
        "destination_location",
        "requested_by",
        "approved_by",
        "dispatched_by",
        "received_by",
    ]
    serializer_class = StockTransferSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .prefetch_related("lines__sku", "lines__batch")
            .order_by("-created_at")
        )

    def current_tenant(self):
        tenant_id = self.tenant_id()
        if not tenant_id:
            raise ValidationError({"tenant": "Select a tenant workspace first."})
        try:
            return Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist as exc:
            raise ValidationError({"tenant": "The selected tenant does not exist."}) from exc

    def tenant_object(self, model, object_id, field):
        try:
            return model.all_objects.get(tenant=self.current_tenant(), pk=object_id)
        except model.DoesNotExist as exc:
            raise ValidationError(
                {field: "The selected record is outside this tenant."}
            ) from exc

    def service_response(self, callback):
        try:
            transfer = callback()
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise ValidationError(exc.message_dict) from exc
            raise ValidationError(
                {"detail": list(getattr(exc, "messages", [str(exc)]))}
            ) from exc
        transfer.refresh_from_db()
        return Response(self.get_serializer(transfer).data)

    def create(self, request, *args, **kwargs):
        payload = StockTransferCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        values = payload.validated_data
        tenant = self.current_tenant()
        source_location = self.tenant_object(
            InventoryLocation,
            values["source_location"],
            "source_location",
        )
        destination_location = self.tenant_object(
            InventoryLocation,
            values["destination_location"],
            "destination_location",
        )
        sku_ids = [line["sku"] for line in values["lines"]]
        skus = {
            sku.pk: sku
            for sku in CommercialSKU.all_objects.filter(
                tenant=tenant,
                pk__in=sku_ids,
                status=CommercialSKU.STATUS_ACTIVE,
            ).select_related("package_definition")
        }
        if len(skus) != len(sku_ids):
            raise ValidationError(
                {"lines": "One or more selected SKUs are unavailable for this tenant."}
            )
        lines = [
            {"sku": skus[line["sku"]], "quantity": line["quantity"]}
            for line in values["lines"]
        ]
        try:
            transfer = StockTransferService.request_transfer(
                tenant=tenant,
                transfer_number=values["transfer_number"].strip(),
                source_branch=source_location.branch,
                dest_branch=destination_location.branch,
                source_location=source_location,
                dest_location=destination_location,
                requested_by=request.user,
                lines_data=lines,
                reason=values.get("reason", ""),
                document_reference=values.get("document_reference", ""),
            )
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise ValidationError(exc.message_dict) from exc
            raise ValidationError(
                {"detail": list(getattr(exc, "messages", [str(exc)]))}
            ) from exc
        return Response(
            self.get_serializer(transfer).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        transfer = self.get_object()
        return self.service_response(
            lambda: StockTransferService.approve_transfer(
                transfer=transfer,
                approver=request.user,
            )
        )

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_transfer(self, request, pk=None):
        transfer = self.get_object()
        return self.service_response(
            lambda: StockTransferService.allocate_and_dispatch(
                transfer=transfer,
                dispatcher=request.user,
            )
        )

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        payload = StockTransferReceiveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        transfer = self.get_object()
        return self.service_response(
            lambda: StockTransferService.receive_transfer(
                transfer=transfer,
                receiver=request.user,
                received_lines_data=payload.validated_data["lines"],
                idempotency_key=payload.validated_data["idempotency_key"],
            )
        )
