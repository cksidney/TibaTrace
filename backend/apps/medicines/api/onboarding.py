from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.tenant_context import get_current_tenant_id
from apps.medicines.onboarding import StaleSetupReview, assert_setup_access, missing_details, save_review, setup_status
from apps.medicines.onboarding_models import LegacyCatalogueItem


class BatchInput(serializers.Serializer):
    batch_number = serializers.CharField(max_length=120)
    expiry_date = serializers.DateField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))


class ReviewInput(serializers.Serializer):
    item_kind = serializers.ChoiceField(choices=["", "MEDICINE", "SUPPLY", "SERVICE"], default="", allow_blank=True)
    sales_unit = serializers.CharField(max_length=80, default="", allow_blank=True)
    pack_description = serializers.CharField(max_length=255, default="", allow_blank=True)
    confirmed_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal(0), required=False, allow_null=True)
    confirmed_cost = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal(0), required=False, allow_null=True)
    counted_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal(0), required=False, allow_null=True)
    counted_on = serializers.DateField(required=False, allow_null=True)
    tax_category = serializers.ChoiceField(choices=["", "STANDARD", "ZERO_RATED", "EXEMPT"], default="", allow_blank=True)
    master_catalogue_code = serializers.CharField(max_length=120, default="", allow_blank=True)
    barcode = serializers.CharField(max_length=100, default="", allow_blank=True)
    notes = serializers.CharField(max_length=4000, default="", allow_blank=True)
    excluded = serializers.BooleanField(default=False)
    batches = BatchInput(many=True, default=list)

    def validate(self, attrs):
        if len(attrs["batches"]) > 100:
            raise serializers.ValidationError("At most 100 batches per item.")
        pairs = [(b["batch_number"], b["expiry_date"]) for b in attrs["batches"]]
        if len(set(pairs)) != len(pairs):
            raise serializers.ValidationError("Combine repeated batch/expiry rows instead of duplicating them.")
        if attrs["item_kind"] == "SERVICE" and attrs["batches"]:
            raise serializers.ValidationError("Services cannot have physical stock batches.")
        return attrs


def serialise(item):
    return {"id":str(item.pk), "source_key":item.source_key, "source_row":item.source_row,
            "legacy_code":item.legacy_code, "proposed_sku_code":item.proposed_sku_code,
            "source_name":item.source_name, "source_uom":item.source_uom,
            "source_cost":str(item.source_cost), "source_price":str(item.source_price),
            "source_quantity":str(item.source_quantity), "source_product":item.source_product,
            "source_stock":item.source_stock, "source_issues":item.source_issues,
            "review":item.review, "status":setup_status(item), "missing_details":missing_details(item),
            "updated_at":item.updated_at.isoformat(), "saleable":False}


class SetupScope(APIView):
    permission_classes = [IsAuthenticated]

    def tenant_id(self, request):
        return get_current_tenant_id() or getattr(request, "tenant_id", None) or request.user.tenant_id

    def scoped(self, request):
        tenant_id = self.tenant_id(request)
        if tenant_id is None:
            return LegacyCatalogueItem.all_objects.none()
        return LegacyCatalogueItem.all_objects.filter(tenant_id=tenant_id)


class LegacyItemList(SetupScope):
    def get(self, request):
        if not any(request.user.has_capability(cap, tenant_id=self.tenant_id(request))
                   for cap in ("inventory.manage", "pricing.manage", "catalogue.manage")):
            return Response({"detail": "Catalogue setup authority is required."}, status=403)
        qs = self.scoped(request).select_related("import_batch")
        summary_items = list(qs)
        summary = {"total":len(summary_items), "positive_stock":sum(i.source_quantity > 0 for i in summary_items),
                   "negative_stock":sum(i.source_quantity < 0 for i in summary_items),
                   "details_complete":sum(setup_status(i) == "DETAILS_COMPLETE" for i in summary_items),
                   "excluded":sum(setup_status(i) == "EXCLUDED" for i in summary_items)}
        query = request.query_params.get("q", "").strip()[:200]
        if query:
            qs = qs.filter(Q(source_name__icontains=query) | Q(legacy_code__icontains=query) | Q(proposed_sku_code__icontains=query))
        if request.query_params.get("stock") == "positive":
            qs = qs.filter(source_quantity__gt=0)
        elif request.query_params.get("stock") == "negative":
            qs = qs.filter(source_quantity__lt=0)
        # Positive stock first. Source row is a stable tie-breaker.
        qs = qs.order_by("-source_quantity", "source_row")
        page = Paginator(qs, 25).get_page(request.query_params.get("page", 1))
        first = summary_items[0] if summary_items else None
        return Response({"summary":summary, "count":page.paginator.count, "page":page.number,
                         "pages":page.paginator.num_pages, "can_edit":bool(self.tenant_id(request) and
                          request.user.has_capability("inventory.manage", tenant_id=self.tenant_id(request))),
                         "source_date":first.import_batch.source_date.isoformat() if first else None,
                         "results":[serialise(i) for i in page]})


class LegacyItemReview(SetupScope):
    def post(self, request, pk):
        item = get_object_or_404(self.scoped(request), pk=pk)
        try:
            assert_setup_access(request.user, item.tenant_id)
        except PermissionDenied as exc:
            return Response({"detail":str(exc)}, status=403)
        serializer = ReviewInput(data=request.data.get("review", {}))
        serializer.is_valid(raise_exception=True)
        # JSON-safe canonical values; preserve Decimal precision as strings.
        review = dict(serializer.data)
        try:
            item = save_review(item=item, actor=request.user, review=review,
                               expected_updated_at=request.data.get("expected_updated_at"))
        except StaleSetupReview as exc:
            return Response({"detail":str(exc)}, status=409)
        except ValidationError as exc:
            return Response({"detail":" ".join(exc.messages)}, status=400)
        return Response(serialise(item))
