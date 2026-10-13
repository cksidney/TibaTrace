from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.inventory.location_services import InventoryLocationProvisioningService
from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
    StocktakeSession,
    StockTransfer,
)
from apps.inventory.services import StocktakeService, StockTransferService
from apps.medicines.models import CommercialSKU
from apps.organizations.models import Location
from apps.tenancy.models import Tenant

from .serializers import (
    InventoryBalanceSerializer,
    InventoryBatchSerializer,
    InventoryLedgerEntrySerializer,
    InventoryLocationProvisionSerializer,
    InventoryLocationSerializer,
    InventoryReservationSerializer,
    StocktakeCountInputSerializer,
    StocktakeEmptyLocationInputSerializer,
    StocktakeOpenSerializer,
    StocktakeReasonInputSerializer,
    StocktakeRevisionInputSerializer,
    StocktakeSessionSerializer,
    StockTransferCreateSerializer,
    StockTransferReceiveSerializer,
    StockTransferSerializer,
)


class InventoryCapabilityPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        tenant_id = getattr(request, "tenant_id", None) or getattr(request.user, "tenant_id", None)
        capabilities = ("inventory.manage",) if request.method not in permissions.SAFE_METHODS else ("inventory.read", "inventory.manage")
        if request.method not in permissions.SAFE_METHODS and isinstance(view, StockTransferViewSet):
            operation = {"create": "request", "approve": "approve", "dispatch_transfer": "dispatch", "receive": "receive"}.get(view.action)
            if operation:
                capabilities += (f"inventory.transfer.{operation}",)
        return bool(tenant_id and any(request.user.has_capability(capability, tenant_id=tenant_id) for capability in capabilities))


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
    permission_classes = [permissions.IsAuthenticated, InventoryCapabilityPermission]

    @action(detail=False, methods=["get"], url_path="branches")
    def branches(self, request):
        tenant_id = self.tenant_id()
        if not tenant_id or not any(
            request.user.has_capability(capability, tenant_id=tenant_id)
            for capability in ("inventory.read", "inventory.manage")
        ):
            raise PermissionDenied("Reading inventory branches requires inventory.read.")
        branches = Location.all_objects.filter(
            tenant_id=tenant_id,
            status="ACTIVE",
            organization__status="ACTIVE",
        ).select_related("organization").order_by("organization__name", "name")
        return Response([
            {
                "id": str(branch.id),
                "name": branch.name,
                "code": branch.code,
                "organization_name": branch.organization.name,
            }
            for branch in branches
        ])

    @action(detail=False, methods=["post"], url_path="provision")
    def provision(self, request):
        tenant_id = self.tenant_id()
        if not tenant_id or not request.user.has_capability("inventory.manage", tenant_id=tenant_id):
            raise PermissionDenied("Storage location provisioning requires inventory.manage.")
        payload = InventoryLocationProvisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        values = payload.validated_data
        branch = Location.all_objects.filter(
            tenant_id=tenant_id,
            pk=values["branch_id"],
            status="ACTIVE",
            organization__status="ACTIVE",
        ).first()
        if branch is None:
            raise ValidationError({"branch_id": "Select an active branch in this tenant."})
        existing = InventoryLocation.all_objects.filter(
            tenant_id=tenant_id,
            branch=branch,
            location_code=values["location_code"].strip().upper(),
        ).exists()
        try:
            location = InventoryLocationProvisioningService.provision_location(
                tenant=Tenant.objects.get(pk=tenant_id),
                branch=branch,
                location_code=values["location_code"],
                name=values["name"],
                location_type=values["location_type"],
                actor=request.user,
            )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages) from exc
        return Response(
            InventoryLocationSerializer(location).data,
            status=status.HTTP_200_OK if existing else status.HTTP_201_CREATED,
        )

class InventoryBatchViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory batches.
    """
    model = InventoryBatch
    select_related = ['sku', 'manufactured_product']
    serializer_class = InventoryBatchSerializer
    permission_classes = [permissions.IsAuthenticated, InventoryCapabilityPermission]

class InventoryLedgerEntryViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing the append-only inventory ledger.
    """
    model = InventoryLedgerEntry
    select_related = ['sku', 'location', 'inventory_batch']
    serializer_class = InventoryLedgerEntrySerializer
    permission_classes = [permissions.IsAuthenticated, InventoryCapabilityPermission]

class InventoryBalanceViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory balances.
    """
    model = InventoryBalance
    select_related = ['sku', 'location']
    serializer_class = InventoryBalanceSerializer
    permission_classes = [permissions.IsAuthenticated, InventoryCapabilityPermission]

class InventoryReservationViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing inventory reservations.
    """
    model = InventoryReservation
    select_related = ['sku', 'source_location', 'batch']
    serializer_class = InventoryReservationSerializer
    permission_classes = [permissions.IsAuthenticated, InventoryCapabilityPermission]


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
    permission_classes = [permissions.IsAuthenticated, InventoryCapabilityPermission]

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


class StocktakeViewSet(mixins.CreateModelMixin, TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = StocktakeSession
    serializer_class = StocktakeSessionSerializer
    permission_classes = [permissions.IsAuthenticated, InventoryCapabilityPermission]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            tenant_id = self.tenant_id()
            if not tenant_id or not any(request.user.has_capability(cap, tenant_id=tenant_id) for cap in ("inventory.read", "inventory.manage")):
                raise PermissionDenied("Stocktake reads require inventory.read authority.")

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("branch", "created_by", "approved_by")
            .prefetch_related("locations", "counts__sku__package_definition", "counts__location", "counts__batch")
            .order_by("-created_at")
        )

    def _require_stocktake_authority(self, request):
        tenant_id = self.tenant_id()
        if not tenant_id or not request.user.has_capability("inventory.manage", tenant_id=tenant_id):
            raise PermissionDenied("Stocktake writes require the inventory.manage capability.")
        return tenant_id

    def _refresh_session(self, session):
        return self.get_queryset().get(pk=session.pk)

    def create(self, request, *args, **kwargs):
        tenant_id = self._require_stocktake_authority(request)
        payload = StocktakeOpenSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        values = payload.validated_data
        branch = Location.all_objects.filter(tenant_id=tenant_id, pk=values["branch_id"]).first()
        if branch is None:
            raise ValidationError({"branch_id": "Select a branch in this tenant."})
        locations = list(
            InventoryLocation.all_objects.filter(
                tenant_id=tenant_id,
                branch=branch,
                pk__in=values["location_ids"],
                status=InventoryLocation.Status.ACTIVE,
            )
        )
        if len(locations) != len(values["location_ids"]):
            raise ValidationError({"location_ids": "Select active inventory locations from the chosen branch."})
        try:
            session = StocktakeService.open_stocktake(
                tenant=Tenant.objects.get(pk=tenant_id),
                branch=branch,
                locations=locations,
                scope=values["scope"],
                creator=request.user,
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": list(getattr(exc, "messages", [str(exc)]))}) from exc
        session.document_number = values.get("document_number", "").strip()
        session.save(update_fields=["document_number", "updated_at"])
        return Response(self.get_serializer(self._refresh_session(session)).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="counts")
    def record_count(self, request, pk=None):
        tenant_id = self._require_stocktake_authority(request)
        payload = StocktakeCountInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        values = payload.validated_data
        session = self.get_object()
        location = InventoryLocation.all_objects.filter(
            tenant_id=tenant_id, pk=values["location_id"], branch_id=session.branch_id
        ).first()
        sku = CommercialSKU.all_objects.filter(
            tenant_id=tenant_id, pk=values["sku_id"]
        ).select_related("package_definition").first()
        batch = None
        if values.get("batch_id"):
            batch = InventoryBatch.all_objects.filter(
                tenant_id=tenant_id, pk=values["batch_id"], sku_id=values["sku_id"]
            ).first()
            if batch is None:
                raise ValidationError({"batch_id": "Select a batch belonging to the selected SKU."})
        if location is None:
            raise ValidationError({"location_id": "Select a location in this stocktake's branch."})
        if sku is None:
            raise ValidationError({"sku_id": "Select a SKU in this tenant, including held/inactive stock that must be physically counted."})
        try:
            StocktakeService.record_count(
                session=session,
                location=location,
                sku=sku,
                batch=batch,
                counted_quantity=values["counted_quantity"],
                counter=request.user,
                reason=values.get("reason", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": list(getattr(exc, "messages", [str(exc)]))}) from exc
        return Response(self.get_serializer(self._refresh_session(session)).data)

    @action(detail=True, methods=["post"], url_path="post-variances")
    def post_variances(self, request, pk=None):
        self._require_stocktake_authority(request)
        session = self.get_object()
        try:
            updated = StocktakeService.post_variances(session=session, approver=request.user)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": list(getattr(exc, "messages", [str(exc)]))}) from exc
        return Response(self.get_serializer(self._refresh_session(updated)).data)

    def _revise_count(self, request, *, void=False):
        self._require_stocktake_authority(request)
        payload = StocktakeRevisionInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        values = payload.validated_data
        if not void and "counted_quantity" not in values:
            raise ValidationError({"counted_quantity": "Enter the new physical count."})
        if void and "counted_quantity" in values:
            raise ValidationError({"counted_quantity": "Voiding does not enter a replacement quantity."})
        session = self.get_object()
        try:
            StocktakeService.revise_count(session=session, actor=request.user, void=void, **values)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": list(getattr(exc, "messages", [str(exc)]))}) from exc
        return Response(self.get_serializer(self._refresh_session(session)).data)

    @action(detail=True, methods=["post"], url_path="recount")
    def recount(self, request, pk=None):
        return self._revise_count(request)

    @action(detail=True, methods=["post"], url_path="void-count")
    def void_count(self, request, pk=None):
        return self._revise_count(request, void=True)

    @action(detail=True, methods=["post"], url_path="confirm-empty-location")
    def confirm_empty_location(self, request, pk=None):
        self._require_stocktake_authority(request)
        payload = StocktakeEmptyLocationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        session = self.get_object()
        try:
            updated = StocktakeService.confirm_empty_location(session=session, actor=request.user, **payload.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": list(getattr(exc, "messages", [str(exc)]))}) from exc
        return Response(self.get_serializer(self._refresh_session(updated)).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        self._require_stocktake_authority(request)
        payload = StocktakeReasonInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        session = self.get_object()
        try:
            updated = StocktakeService.cancel(session=session, actor=request.user, **payload.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": list(getattr(exc, "messages", [str(exc)]))}) from exc
        return Response(self.get_serializer(self._refresh_session(updated)).data)
