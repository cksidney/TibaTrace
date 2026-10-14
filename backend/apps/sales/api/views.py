from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.core.permissions import CapabilityPermission
from apps.core.tenant_context import get_current_tenant_id
from apps.customers.models import Customer, CustomerDeliveryAddress
from apps.medicines.models import CommercialSKU
from apps.organizations.models import Location
from apps.sales.api.fulfilment import command
from apps.sales.api.serializers import (
    CommercialArchiveSerializer,
    CommercialDraftCloneSerializer,
    CommercialPriceCommandSerializer,
    CustomerPriceAgreementSerializer,
    DeliveryRecordSerializer,
    DispatchOrderSerializer,
    OrderLineCreateSerializer,
    PackageSerializer,
    PackingSessionSerializer,
    PickingTaskSerializer,
    PickingWaveSerializer,
    PriceListEntrySerializer,
    PriceListSerializer,
    PromotionRuleSerializer,
    QuotationCreateSerializer,
    QuotationSerializer,
    SalesOrderAllocationSerializer,
    SalesOrderCreateSerializer,
    SalesOrderHoldSerializer,
    SalesOrderSerializer,
    SalesReturnAuthorizationSerializer,
    SalesReturnRequestSerializer,
    SubstitutionProposalSerializer,
    SubstitutionProposeSerializer,
)
from apps.sales.commercial_governance import CommercialPriceGovernanceService
from apps.sales.models import (
    CustomerPriceAgreement,
    DeliveryRecord,
    DispatchOrder,
    Package,
    PackingSession,
    PickingTask,
    PickingWave,
    PriceList,
    PriceListEntry,
    PromotionRule,
    Quotation,
    SalesOrder,
    SalesOrderAllocation,
    SalesOrderHold,
    SalesOrderLine,
    SalesReturnAuthorization,
)
from apps.sales.services import (
    DeliveryService,
    DispatchService,
    PackingService,
    PickingService,
    PickingWaveService,
    QuotationService,
    SalesAllocationService,
    SalesApprovalService,
    SalesOrderService,
    SalesReservationService,
    SalesReturnService,
    SubstitutionProposalService,
)
from apps.tenancy.models import Tenant


def _tenant_scoped(model, tenant_id, pk, field):
    """Fetch a related record inside the caller's tenant, or refuse by name.

    all_objects with an explicit tenant filter, not the strict manager: these run
    in a request where tenant context exists, but naming the filter keeps the
    isolation on a line you can read rather than in a thread-local.
    """
    obj = model.all_objects.filter(tenant_id=tenant_id, pk=pk).first()
    if obj is None:
        raise DRFValidationError({field: [f"Unknown {field}."]})
    return obj


class BaseSalesViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only, with state changes routed through the service actions.

    These were ModelViewSets: a generic PATCH could set a sales order's status,
    release a hold or mark a delivery without the service that enforces
    allocation, credit and proof-of-delivery rules. The HQ client only calls the
    actions, so the generic path was an unused second route to every control.

    Pricing is deliberately excluded -- see WritablePricingViewSet below.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        self.required_capabilities = ("sales.read", "sales.manage") if self.request.method in {"GET", "HEAD", "OPTIONS"} else ("sales.manage",)
        return [permissions.IsAuthenticated(), CapabilityPermission()]

    def get_queryset(self):
        tenant_id = get_current_tenant_id() or getattr(self.request, "tenant_id", None)
        if not tenant_id and hasattr(self.request.user, "tenant_id"):
            tenant_id = self.request.user.tenant_id
        if tenant_id:
            # all_objects with an explicit tenant filter. The default manager is
            # tenant-strict and returns nothing unless tenant context has been
            # set on the thread, which does not happen for an ordinary API
            # request -- so every sales collection came back empty and every
            # detail route 404'd for data that exists.
            return self.model.all_objects.filter(tenant_id=tenant_id)
        return self.model.all_objects.none()

    def _tenant_id(self):
        return (
            get_current_tenant_id()
            or getattr(self.request, "tenant_id", None)
            or getattr(self.request.user, "tenant_id", None)
        )

    def perform_create(self, serializer):
        tenant_id = (
            get_current_tenant_id()
            or getattr(self.request, "tenant_id", None)
            or getattr(self.request.user, "tenant_id", None)
        )
        serializer.save(tenant_id=tenant_id)


class WritablePricingViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin,
                             mixins.DestroyModelMixin, BaseSalesViewSet):
    """Writable, deliberately, and only these.

    PriceListEntry is the live business-to-business price table: `price_line` in
    apps/sales/services.py prices every quotation and sales-order line from it,
    honouring customer agreements, quantity breaks and effective dates. Making it
    read-only would stop price maintenance, so it keeps its writes while the
    order and fulfilment surfaces do not.

    Only drafts may be edited. Independent review and publication bind the
    exact contents; active lists remain immutable and history cannot be deleted.
    """

    def get_permissions(self):
        self.required_capabilities = ("pricing.read", "pricing.manage", "pricing.commercial.approve", "pricing.commercial.publish") if self.request.method in {"GET", "HEAD", "OPTIONS"} else ("pricing.manage",)
        return [permissions.IsAuthenticated(), CapabilityPermission()]

    def _retry_safe_write(self, request, write):
        import hashlib
        import json
        from collections.abc import Mapping

        from django.db import transaction

        from apps.workflows.models import DomainEvent
        from apps.workflows.service import emit_event

        if not isinstance(request.data, Mapping):
            raise DRFValidationError("Send a JSON object containing commercial price details.")
        key = str(request.data.get("idempotency_key") or "").strip()
        if len(key) > 128:
            raise DRFValidationError("Command key must not exceed 128 characters.")
        details = [self.model._meta.label, request.method, self.kwargs.get("pk"), str(request.user.pk), request.data]
        request_hash = hashlib.sha256(json.dumps(details, sort_keys=True, default=str).encode()).hexdigest()
        with transaction.atomic():
            # Validate uniqueness only after serialising writes, and return an
            # already recorded result before serializer uniqueness checks.
            Tenant.objects.select_for_update().get(pk=self._tenant_id())
            if key:
                prior = DomainEvent.all_objects.filter(tenant_id=self._tenant_id(), aggregate_type="B2B_PRICE_COMMAND", payload__idempotency_key=key).first()
                if prior:
                    if prior.payload["request_hash"] != request_hash:
                        raise DRFValidationError("This command key belongs to different price details or another actor.")
                    record = self.model.all_objects.get(tenant_id=self._tenant_id(), pk=prior.aggregate_id)
                    return Response(self.get_serializer(record).data, status=prior.payload["response_status"])
            response = write()
            if key:
                emit_event(tenant_id=self._tenant_id(), aggregate_type="B2B_PRICE_COMMAND", aggregate_id=str(response.data["id"]),
                    event_type="B2B_PRICE_DRAFT_WRITTEN", payload={"actor_id": str(request.user.pk), "model": self.model._meta.label,
                        "idempotency_key": key, "request_hash": request_hash, "response_status": response.status_code})
            return response

    def create(self, request, *args, **kwargs):
        return self._retry_safe_write(request, lambda: super(WritablePricingViewSet, self).create(request, *args, **kwargs))

    def update(self, request, *args, **kwargs):
        return self._retry_safe_write(request, lambda: super(WritablePricingViewSet, self).update(request, *args, **kwargs))

    def _reason(self):
        reason = str(self.request.data.get("change_reason", "")).strip()
        if not reason:
            raise DRFValidationError({"change_reason": "Explain the pricing change."})
        return reason[:1000]

    def _audit(self, instance, reason):
        import json

        from django.core.serializers.json import DjangoJSONEncoder

        from apps.audit.service import log_audit

        log_audit(tenant_id=self._tenant_id(), actor_id=self.request.user.pk,
                  action="B2B_PRICE_CHANGED", model_name=instance._meta.label, object_id=str(instance.pk),
                  metadata={"reason": reason, "method": self.request.method,
                            "recorded_contents": json.loads(json.dumps(self.get_serializer(instance).data, cls=DjangoJSONEncoder))})

    def perform_create(self, serializer):
        from django.db import transaction

        from apps.sales.commercial_governance import require
        with transaction.atomic():
            require(self.request.user, self._tenant_id(), "pricing.manage")
            reason = self._reason()
            if self.model == PriceListEntry:
                price_list = PriceList.all_objects.select_for_update().get(tenant_id=self._tenant_id(), pk=serializer.validated_data["price_list"].pk)
                self._draft_only(price_list)
            instance = serializer.save(tenant_id=self._tenant_id())
            self._audit(instance, reason)

    def perform_update(self, serializer):
        from django.db import transaction
        with transaction.atomic():
            record = serializer.instance
            anchor = record if self.model == PriceList else record.price_list
            anchor = PriceList.all_objects.select_for_update().get(tenant_id=self._tenant_id(), pk=anchor.pk)
            self._draft_only(anchor)
            # Re-read after locking so concurrent writes cannot replace fields
            # from a stale serializer instance.
            serializer.instance = self.model.all_objects.get(tenant_id=self._tenant_id(), pk=record.pk)
            instance = serializer.save()
            self._audit(instance, self._reason())

    def perform_destroy(self, instance):
        raise DRFValidationError("Commercial price history cannot be deleted. Archive a list or deactivate a draft entry with a reason.")

    @staticmethod
    def _draft_only(price_list):
        if price_list.status != "DRAFT":
            raise DRFValidationError("Active or archived commercial prices are immutable. Create a new draft list.")


class PriceListViewSet(WritablePricingViewSet):
    model = PriceList
    serializer_class = PriceListSerializer

    @action(detail=False, methods=["get"], url_path="workspace-options")
    def workspace_options(self, request):
        from django.db.models import F, Q
        tenant_id = self._tenant_id()
        query = str(request.query_params.get("q") or "").strip()[:150]
        skus = CommercialSKU.all_objects.filter(tenant_id=tenant_id)
        if query:
            skus = skus.filter(Q(sku_code__icontains=query) | Q(display_name__icontains=query))
        rows = list(skus.annotate(sales_unit=F("package_definition__unit_of_measure")).order_by("sku_code").values("id", "sku_code", "display_name", "sales_unit", "status")[:1001])
        return Response({"skus": rows[:1000], "more_skus": len(rows) > 1000,
            "can_edit": request.user.has_capability("pricing.manage", tenant_id=tenant_id),
            "can_approve": request.user.has_capability("pricing.commercial.approve", tenant_id=tenant_id),
            "can_publish": request.user.has_capability("pricing.commercial.publish", tenant_id=tenant_id)})

    @action(detail=True, methods=["post"], url_path="new-draft")
    def new_draft(self, request, pk=None):
        payload = CommercialDraftCloneSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = CommercialPriceGovernanceService.clone(price_list=self.get_object(), actor=request.user, **payload.validated_data)
        return Response(self.get_serializer(row).data, status=201)

    def get_permissions(self):
        if self.action in {"govern", "archive"}:
            self.required_capabilities = ("pricing.manage", "pricing.commercial.approve", "pricing.commercial.publish")
            return [permissions.IsAuthenticated(), CapabilityPermission()]
        return super().get_permissions()

    @action(detail=True, methods=["post"])
    def govern(self, request, pk=None):
        payload = CommercialPriceCommandSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = CommercialPriceGovernanceService.run(price_list=self.get_object(), actor=request.user, **payload.validated_data)
        return Response(self.get_serializer(row).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        payload = CommercialArchiveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = CommercialPriceGovernanceService.archive(price_list=self.get_object(), actor=request.user, **payload.validated_data)
        return Response(self.get_serializer(row).data)


class PriceListEntryViewSet(WritablePricingViewSet):
    model = PriceListEntry
    serializer_class = PriceListEntrySerializer

    def get_queryset(self):
        return super().get_queryset().select_related("sku", "price_list")


class PromotionRuleViewSet(BaseSalesViewSet):
    model = PromotionRule
    serializer_class = PromotionRuleSerializer


class CustomerPriceAgreementViewSet(BaseSalesViewSet):
    model = CustomerPriceAgreement
    serializer_class = CustomerPriceAgreementSerializer


class QuotationViewSet(BaseSalesViewSet):
    model = Quotation
    serializer_class = QuotationSerializer

    def create(self, request, *args, **kwargs):
        """Raise a quotation through the service.

        Creation was previously the generic ModelViewSet POST, which wrote the
        row straight from the serializer and skipped create_quotation entirely --
        no numbering, no tenant checks on branch and customer, no pricing. That
        path is closed; this is the governed one.
        """
        payload = QuotationCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tenant_id = self._tenant_id()
        quotation = QuotationService.create_quotation(
            tenant=Tenant.objects.get(pk=tenant_id),
            branch=_tenant_scoped(Location, tenant_id, payload.validated_data["branch"], "branch"),
            customer=_tenant_scoped(Customer, tenant_id, payload.validated_data["customer"], "customer"),
            currency=payload.validated_data["currency"],
            customer_reference=payload.validated_data["customer_reference"],
            notes=payload.validated_data["notes"],
            terms=payload.validated_data["terms"],
            valid_until=payload.validated_data["valid_until"],
            created_by=request.user,
        )
        return Response(self.get_serializer(quotation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="lines")
    def add_line(self, request, pk=None):
        payload = OrderLineCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        quotation = self.get_object()
        QuotationService.add_quotation_line(
            quotation=quotation,
            sku=_tenant_scoped(CommercialSKU, quotation.tenant_id, payload.validated_data["sku"], "sku"),
            requested_quantity=payload.validated_data["requested_quantity"],
            unit=payload.validated_data["unit"],
        )
        quotation.refresh_from_db()
        return Response(self.get_serializer(quotation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        obj = self.get_object()
        QuotationService.reject_quotation(quotation=obj)
        obj.refresh_from_db()
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        obj = self.get_object()
        QuotationService.submit_quotation(quotation=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        QuotationService.approve_quotation(quotation=obj, approver=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        obj = self.get_object()
        QuotationService.send_quotation(quotation=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        obj = self.get_object()
        QuotationService.accept_quotation(quotation=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        obj = self.get_object()
        order = QuotationService.convert_quotation(quotation=obj, actor=request.user)
        return Response({"sales_order_id": order.id}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        obj = self.get_object()
        QuotationService.revise_quotation(
            quotation=obj,
            changed_fields=request.data.get("changed_fields", []),
            new_values=request.data.get("new_values", {}),
            reason=request.data.get("reason", ""),
            actor=request.user,
        )
        return Response(self.get_serializer(obj).data)


class SalesOrderViewSet(BaseSalesViewSet):
    model = SalesOrder
    serializer_class = SalesOrderSerializer

    @action(detail=False, methods=["get"], url_path="workspace-options")
    def workspace_options(self, request):
        tenant_id = self._tenant_id()
        return Response({
            "branches": list(Location.all_objects.filter(tenant_id=tenant_id, status="ACTIVE", organization__status="ACTIVE").order_by("name").values("id", "name", "code")),
            "customers": list(Customer.all_objects.filter(tenant_id=tenant_id, status="ACTIVE").order_by("legal_name").values("id", "legal_name", "customer_number")),
            "addresses": list(CustomerDeliveryAddress.all_objects.filter(tenant_id=tenant_id, is_active=True, customer__status="ACTIVE").order_by("address_code").values("id", "customer_id", "address_code", "address_line1", "city")),
        })

    @action(detail=True, methods=["post"], url_path="picking-wave")
    def picking_wave(self, request, pk=None):
        def create(order):
            allocations = list(SalesOrderAllocation.all_objects.filter(tenant=order.tenant, sales_order_line__sales_order=order,
                status="ALLOCATED").select_related("sales_order_line__sku", "inventory_batch", "location"))
            if not allocations:
                raise DRFValidationError("Allocate actual stock before creating a picking wave.")
            if PickingTask.all_objects.filter(tenant=order.tenant, sales_order=order).exists():
                raise DRFValidationError("This order already has picking tasks. Continue its existing wave.")
            wave = PickingWaveService.create_wave(tenant=order.tenant, branch=order.branch, scope={"sales_order_id":str(order.pk)}, created_by=request.user)
            wave = PickingWaveService.release_wave(wave=wave)
            for allocation in allocations:
                PickingService.create_picking_task(tenant=order.tenant, sales_order=order, sales_order_line=allocation.sales_order_line,
                    allocation=allocation, source_location=allocation.location, sku=allocation.sales_order_line.sku,
                    batch=allocation.inventory_batch, requested_quantity=allocation.quantity, picking_wave=wave)
            return PickingWaveSerializer(wave).data
        return command(request, self.get_object(), "HQPickingWaveCreated", create)

    @action(detail=True, methods=["post"], url_path="packing-session")
    def packing_session(self, request, pk=None):
        return command(request, self.get_object(), "HQPackingSessionCreated", lambda order: PackingSessionSerializer(
            PackingService.create_session(tenant=order.tenant, branch=order.branch, sales_order=order, packer=request.user)).data)

    @action(detail=True, methods=["post"], url_path="create-dispatch")
    def create_dispatch(self, request, pk=None):
        def create(order):
            address = _tenant_scoped(CustomerDeliveryAddress, order.tenant_id, request.data.get("delivery_address_id"), "delivery_address_id")
            package_ids = request.data.get("package_ids", [])
            if not isinstance(package_ids, list) or not package_ids or len(set(package_ids)) != len(package_ids):
                raise DRFValidationError("Select one or more distinct sealed packages.")
            packages = list(Package.all_objects.filter(tenant=order.tenant, sales_order=order, pk__in=package_ids, status="SEALED").prefetch_related("lines"))
            if len(packages) != len(package_ids):
                raise DRFValidationError("Every package must be sealed and belong to this order.")
            dispatch = DispatchService.create_dispatch(tenant=order.tenant, branch=order.branch, customer=order.customer,
                delivery_address=address, sales_order=order, carrier=str(request.data.get("carrier", ""))[:200], created_by=request.user)
            for package in packages:
                for line in package.lines.all():
                    DispatchService.add_dispatch_line(dispatch=dispatch, sales_order_line=line.sales_order_line, package=package,
                        sku=line.sku, batch=line.batch, quantity=line.quantity, unit=line.unit,
                        idempotency_key=f"HQ_DISPATCH:{dispatch.pk}:{line.pk}")
            return DispatchOrderSerializer(dispatch).data
        return command(request, self.get_object(), "HQDispatchCreated", create)

    def create(self, request, *args, **kwargs):
        """Raise a sales order through the service.

        The generic POST that used to do this wrote the row from the serializer,
        skipping the tenant checks on branch, customer and delivery address, the
        numbering, and the policies that govern partial fulfilment, substitution
        and invoicing. Those policies decide whether a medicine may be swapped;
        they are not form defaults.
        """
        payload = SalesOrderCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tenant_id = self._tenant_id()
        data = payload.validated_data
        source = (
            _tenant_scoped(Quotation, tenant_id, data["source_quotation"], "source_quotation")
            if data["source_quotation"] else None
        )
        order = SalesOrderService.create_sales_order(
            tenant=Tenant.objects.get(pk=tenant_id),
            branch=_tenant_scoped(Location, tenant_id, data["branch"], "branch"),
            customer=_tenant_scoped(Customer, tenant_id, data["customer"], "customer"),
            currency=data["currency"],
            customer_po_reference=data["customer_po_reference"],
            requested_delivery_date=data["requested_delivery_date"],
            fulfilment_policy=data["fulfilment_policy"],
            substitution_policy=data["substitution_policy"],
            invoice_policy=data["invoice_policy"],
            source_quotation=source,
            created_by=request.user,
        )
        return Response(self.get_serializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="lines")
    def add_line(self, request, pk=None):
        payload = OrderLineCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order = self.get_object()
        SalesOrderService.add_order_line(
            sales_order=order,
            sku=_tenant_scoped(CommercialSKU, order.tenant_id, payload.validated_data["sku"], "sku"),
            requested_quantity=payload.validated_data["requested_quantity"],
            unit=payload.validated_data["unit"],
        )
        order.refresh_from_db()
        return Response(self.get_serializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="substitutions")
    def propose_substitution(self, request, pk=None):
        """Propose swapping one medicine for another on an order line.

        Routed because it is a clinical decision, not a stock convenience. The
        service refuses it outright when the order's substitution policy forbids
        it, and the proposal needs separate approval before it takes effect.
        """
        payload = SubstitutionProposeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order = self.get_object()
        line = _tenant_scoped(
            SalesOrderLine, order.tenant_id,
            payload.validated_data["sales_order_line"], "sales_order_line",
        )
        proposal = SubstitutionProposalService.propose_substitution(
            sales_order_line=line,
            proposed_sku=_tenant_scoped(
                CommercialSKU, order.tenant_id,
                payload.validated_data["proposed_sku"], "proposed_sku",
            ),
            reason=payload.validated_data["reason"],
            actor=request.user,
        )
        return Response(
            SubstitutionProposalSerializer(proposal).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        obj = self.get_object()
        SalesOrderService.submit_order(sales_order=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        SalesApprovalService.approve_order(sales_order=obj, approver=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def hold(self, request, pk=None):
        obj = self.get_object()
        SalesApprovalService.place_hold(
            sales_order=obj,
            hold_type=request.data.get("hold_type"),
            reason=request.data.get("reason", ""),
            placed_by=request.user,
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def release_hold(self, request, pk=None):
        obj = self.get_object()
        hold_id = request.data.get("hold_id")
        # Already filtered by sales_order and tenant, so the strict manager adds
        # nothing but a DoesNotExist for a hold that plainly exists.
        hold = SalesOrderHold.all_objects.get(
            id=hold_id, sales_order=obj, tenant=obj.tenant
        )
        SalesApprovalService.release_hold(
            hold=hold, released_by=request.user, release_reason=request.data.get("release_reason", "")
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        obj = self.get_object()
        SalesReservationService.reserve_order(sales_order=obj, actor=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        obj = self.get_object()
        SalesAllocationService.allocate_order(sales_order=obj, actor=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        obj = self.get_object()
        result = SalesOrderService.cancel_order(
            sales_order=obj, reason=request.data.get("reason", ""), actor=request.user
        )
        return Response(self.get_serializer(result).data)


class SalesOrderHoldViewSet(BaseSalesViewSet):
    model = SalesOrderHold
    serializer_class = SalesOrderHoldSerializer


class SalesOrderAllocationViewSet(BaseSalesViewSet):
    model = SalesOrderAllocation
    serializer_class = SalesOrderAllocationSerializer


class PickingWaveViewSet(BaseSalesViewSet):
    model = PickingWave
    serializer_class = PickingWaveSerializer

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        obj = self.get_object()
        PickingWaveService.release_wave(wave=obj)
        return Response(self.get_serializer(obj).data)


class PickingTaskViewSet(BaseSalesViewSet):
    model = PickingTask
    serializer_class = PickingTaskSerializer

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        obj = self.get_object()
        result = PickingService.assign_task(task=obj, picker=request.user)
        return Response(self.get_serializer(result).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        obj = self.get_object()
        if obj.assigned_picker_id != request.user.pk:
            raise DRFValidationError("Only the assigned picker may start this physical pick.")
        PickingService.start_task(task=obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def record(self, request, pk=None):
        obj = self.get_object()
        if obj.assigned_picker_id != request.user.pk:
            raise DRFValidationError("Only the assigned picker may record physical quantities.")
        PickingService.record_pick(
            task=obj,
            picked_quantity=request.data.get("picked_quantity", 0),
            short_quantity=request.data.get("short_quantity", 0),
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        obj = self.get_object()
        PickingService.verify_pick(task=obj, verifier=request.user)
        return Response(self.get_serializer(obj).data)


class PackingSessionViewSet(BaseSalesViewSet):
    model = PackingSession
    serializer_class = PackingSessionSerializer

    @action(detail=True, methods=["post"], url_path="create-package")
    def create_package(self, request, pk=None):
        def create(session):
            zone = request.data.get("temperature_zone", "AMBIENT")
            if zone not in {"AMBIENT", "COLD_CHAIN", "FROZEN"}:
                raise DRFValidationError("Confirm an actual package temperature zone.")
            return PackageSerializer(PackingService.create_package(session=session, sales_order=session.sales_order,
                temperature_zone=zone, package_type=str(request.data.get("package_type", ""))[:100], packer=request.user)).data
        return command(request, self.get_object(), "HQPackageCreated", create)


class PackageViewSet(BaseSalesViewSet):
    model = Package
    serializer_class = PackageSerializer

    @action(detail=True, methods=["post"], url_path="pack-line")
    def pack_line(self, request, pk=None):
        def pack(package):
            task = _tenant_scoped(PickingTask, package.tenant_id, request.data.get("picking_task_id"), "picking_task_id")
            if task.sales_order_id != package.sales_order_id:
                raise DRFValidationError("The selected picking task belongs to another order.")
            PackingService.pack_line(package=package, sales_order_line=task.sales_order_line, picking_task=task,
                sku=task.sku, batch=task.batch, quantity=request.data.get("quantity", ""), unit=task.sales_order_line.unit)
            return PackageSerializer(package).data
        return command(request, self.get_object(), "HQPackageLinePacked", pack)

    @action(detail=True, methods=["post"])
    def seal(self, request, pk=None):
        obj = self.get_object()
        if not str(request.data.get("seal_number", "")).strip():
            raise DRFValidationError({"seal_number":"Record the actual tamper-seal number."})
        PackingService.seal_package(package=obj, seal_number=request.data.get("seal_number", ""), verifier=request.user)
        return Response(self.get_serializer(obj).data)


class DispatchOrderViewSet(BaseSalesViewSet):
    model = DispatchOrder
    serializer_class = DispatchOrderSerializer

    @action(detail=True, methods=["post"], url_path="delivery")
    def delivery(self, request, pk=None):
        dispatch = self.get_object()
        return command(request, dispatch, "HQDeliveryRecorded", lambda locked: DeliveryRecordSerializer(DeliveryService.confirm_delivery(
            dispatch=locked, recipient_name=str(request.data.get("recipient_name", "")).strip(),
            recipient_role=str(request.data.get("recipient_role", "")), recipient_phone=str(request.data.get("recipient_phone", "")),
            proof_type=str(request.data.get("proof_type", "")), signature_ref=str(request.data.get("signature_ref", "")),
            photo_ref=str(request.data.get("photo_ref", "")), coordinates=str(request.data.get("coordinates", "")),
            temperature_evidence=str(request.data.get("temperature_evidence", "")), delivery_notes=str(request.data.get("delivery_notes", "")),
            recorded_by=request.user, delivery_lines_data=request.data.get("delivery_lines_data", []),
            idempotency_key=str(request.data.get("idempotency_key", "")))).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        DispatchService.approve_dispatch(dispatch=obj, approver=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def load(self, request, pk=None):
        obj = self.get_object()
        packages = request.data.get("packages")
        if packages is None:
            packages = list(
                obj.lines.values_list("package_id", flat=True).distinct()
            )
        DispatchService.load_dispatch(
            dispatch=obj,
            packages=packages,
            loaded_by=request.user,
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_action(self, request, pk=None):
        obj = self.get_object()
        result = DispatchService.dispatch_order(dispatch=obj, dispatched_by=request.user)
        return Response(self.get_serializer(result).data)


class DeliveryRecordViewSet(BaseSalesViewSet):
    model = DeliveryRecord
    serializer_class = DeliveryRecordSerializer

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        obj = self.get_object()
        result = DeliveryService.confirm_delivery(
            dispatch=obj.dispatch_order,
            recipient_name=request.data.get("recipient_name", ""),
            recipient_role=request.data.get("recipient_role", ""),
            recipient_phone=request.data.get("recipient_phone", ""),
            proof_type=request.data.get("proof_type", ""),
            signature_ref=request.data.get("signature_ref", ""),
            photo_ref=request.data.get("photo_ref", ""),
            coordinates=request.data.get("coordinates", ""),
            temperature_evidence=request.data.get("temperature_evidence", ""),
            delivery_notes=request.data.get("delivery_notes", ""),
            recorded_by=request.user,
            delivery_lines_data=request.data.get("delivery_lines_data", []),
            idempotency_key=request.data.get("idempotency_key"),
        )
        return Response(self.get_serializer(result).data)

    @action(detail=True, methods=["post"])
    def fail(self, request, pk=None):
        obj = self.get_object()
        result = DeliveryService.record_failed_delivery(
            dispatch=obj.dispatch_order,
            failure_reason=request.data.get("failure_reason", ""),
            recorded_by=request.user,
            idempotency_key=request.data.get("idempotency_key"),
        )
        return Response(self.get_serializer(result).data)


class SalesReturnAuthorizationViewSet(BaseSalesViewSet):
    model = SalesReturnAuthorization
    serializer_class = SalesReturnAuthorizationSerializer

    def create(self, request, *args, **kwargs):
        """Raise a return against a delivered order, through the service."""
        payload = SalesReturnRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tenant_id = self._tenant_id()
        order = _tenant_scoped(
            SalesOrder, tenant_id, payload.validated_data["sales_order"], "sales_order"
        )
        authorisation = SalesReturnService.request_return(
            sales_order=order,
            customer=order.customer,
            reason=payload.validated_data["reason"],
            requested_by=request.user,
        )
        return Response(
            self.get_serializer(authorisation).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        SalesReturnService.approve_return(return_auth=obj, approver=request.user)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        obj = self.get_object()
        SalesReturnService.receive_return(
            return_auth=obj,
            received_quantities=request.data.get("received_quantities", {}),
            received_by=request.user,
        )
        return Response(self.get_serializer(obj).data)
