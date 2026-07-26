"""Pricing workbench and price-resolution query.

Read-only, with one computed endpoint. `resolve` answers "what would this cost
here today" and writes nothing -- no snapshot, no lock, no override. A quote is
not a sale, and an endpoint that recorded one every time somebody looked at a
price would fill the applied-price table with charges that never happened.

Resolution refuses rather than guessing. Both refusals are 409 rather than 200
with a null price: a client that receives a price field is entitled to treat it
as a price, and there is no value that safely means "we could not work this
out".
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.pricing.catalogue import PriceCatalogue
from apps.pricing.models import (
    AppliedPriceSnapshot,
    ManualPriceOverride,
    PriceAssignment,
    PriceBook,
    PriceBookEntry,
    PriceBookVersion,
    PriceLock,
)
from apps.pricing.resolution import AmbiguousPricing, NoPriceFound, PricingContext, PricingError

from .serializers import (
    AppliedPriceSnapshotSerializer,
    ManualPriceOverrideSerializer,
    PriceAssignmentSerializer,
    PriceBookEntrySerializer,
    PriceBookSerializer,
    PriceBookVersionSerializer,
    PriceLockSerializer,
)


class TenantScopedReadOnly(viewsets.ReadOnlyModelViewSet):
    """Read-only and tenant-scoped by construction.

    The scoping lives here rather than in each subclass, so adding an endpoint
    cannot leak by forgetting a filter.
    """

    permission_classes = [permissions.IsAuthenticated]
    model = None

    def tenant_id(self):
        request = self.request
        return (
            getattr(request, "tenant_id", None)
            or getattr(getattr(request, "tenant", None), "pk", None)
            or getattr(request.user, "tenant_id", None)
        )

    def get_queryset(self):
        tenant_id = self.tenant_id()
        if tenant_id is None:
            # A price list is commercially sensitive. No tenant, no rows.
            return self.model.all_objects.none()
        return self.model.all_objects.filter(tenant_id=tenant_id)


class PriceBookViewSet(TenantScopedReadOnly):
    model = PriceBook
    serializer_class = PriceBookSerializer


class PriceBookVersionViewSet(TenantScopedReadOnly):
    model = PriceBookVersion
    serializer_class = PriceBookVersionSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("price_book")
        book = self.request.query_params.get("price_book")
        if book:
            queryset = queryset.filter(price_book_id=book)
        return queryset


class PriceBookEntryViewSet(TenantScopedReadOnly):
    model = PriceBookEntry
    serializer_class = PriceBookEntrySerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("sku", "version")
        version = self.request.query_params.get("version")
        if version:
            queryset = queryset.filter(version_id=version)
        sku = self.request.query_params.get("sku")
        if sku:
            queryset = queryset.filter(sku_id=sku)
        return queryset


class PriceAssignmentViewSet(TenantScopedReadOnly):
    model = PriceAssignment
    serializer_class = PriceAssignmentSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("price_book")
        branch = self.request.query_params.get("branch")
        if branch:
            queryset = queryset.filter(branch_id=branch)
        return queryset


class AppliedPriceViewSet(TenantScopedReadOnly):
    """What lines were actually charged.

    The audit surface. It exists so somebody can answer what a customer paid
    without re-resolving today's prices against yesterday's sale.
    """

    model = AppliedPriceSnapshot
    serializer_class = AppliedPriceSnapshotSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("sku").order_by("-resolved_at")
        for parameter, field in (("sku", "sku_id"), ("branch", "branch_id"),
                                 ("line", "line_reference")):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset


class ManualPriceOverrideViewSet(TenantScopedReadOnly):
    """Override history.

    Requesting and approving happen through PriceOverrideService, which checks
    the floor, the capability and that the approver is not the requester. This
    endpoint is how somebody reviews what was granted.
    """

    model = ManualPriceOverride
    serializer_class = ManualPriceOverrideSerializer

    def get_queryset(self):
        queryset = (
            super().get_queryset()
            .select_related("sku", "requested_by", "approved_by")
            .order_by("-created_at")
        )
        if self.request.query_params.get("pending") == "true":
            queryset = queryset.filter(status=ManualPriceOverride.Status.REQUESTED)
        return queryset


class PriceLockViewSet(TenantScopedReadOnly):
    model = PriceLock
    serializer_class = PriceLockSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("sku")
        basket = self.request.query_params.get("basket")
        if basket:
            queryset = queryset.filter(basket_reference=basket)
        return queryset


class PriceResolutionViewSet(viewsets.ViewSet):
    """Ask what something costs, without recording that you asked."""

    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="resolve")
    def resolve(self, request):
        """Resolve a price for a branch, item, quantity and date.

        A GET, because it changes nothing. Making it a POST would invite an
        implementation that records the quote, and a quote is not a sale.
        """
        tenant_id = (
            getattr(request, "tenant_id", None)
            or getattr(getattr(request, "tenant", None), "pk", None)
            or getattr(request.user, "tenant_id", None)
        )
        params = request.query_params

        try:
            quantity = Decimal(str(params.get("quantity", "1")))
        except (InvalidOperation, ValueError):
            return Response(
                {"detail": "quantity must be a decimal number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service_date = params.get("service_date")
        try:
            resolved_date = date.fromisoformat(service_date) if service_date else date.today()
        except ValueError:
            return Response(
                {"detail": "service_date must be an ISO date."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            context = PricingContext(
                tenant_id=str(tenant_id or ""),
                branch_id=params.get("branch", ""),
                sku_id=params.get("sku", ""),
                service_date=resolved_date,
                quantity=quantity,
                currency=params.get("currency", "KES"),
                customer_id=params.get("customer") or None,
                customer_segment=params.get("customer_segment") or None,
                insurer_id=params.get("insurer") or None,
                branch_group_id=params.get("branch_group") or None,
            )
        except PricingError as exc:
            # Missing branch, tenant or date. Refusing beats resolving from an
            # item alone, which is how one branch's price reaches another's till.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            resolved = PriceCatalogue.price(context=context)
        except AmbiguousPricing as exc:
            # 409: the configuration is in conflict and a human must fix it.
            return Response(
                {"detail": str(exc), "code": "AMBIGUOUS_PRICING"},
                status=status.HTTP_409_CONFLICT,
            )
        except NoPriceFound as exc:
            # Also 409, not 200 with a null. A client receiving a price field is
            # entitled to treat it as a price.
            return Response(
                {"detail": str(exc), "code": "NO_PRICE_FOUND"},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "unit_price": str(resolved.unit_price),
                "currency": resolved.currency,
                "source": resolved.source,
                "source_reference": resolved.reference,
                "tax_inclusive": resolved.tax_inclusive,
                "explanation": resolved.explain(),
                "considered": list(resolved.considered),
                "context_hash": resolved.context_hash,
            }
        )
