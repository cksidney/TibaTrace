from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.tenant_context import get_current_tenant_id
from apps.medicines.onboarding import StaleSetupReview, assert_setup_access, missing_details, save_review, setup_status
from apps.medicines.onboarding_completion import release_opening_setup, stage_opening_setup
from apps.medicines.onboarding_models import LegacyCatalogueImport, LegacyCatalogueItem
from apps.medicines.onboarding_upload import import_item_upload, opening_stocktake_csv
from apps.tenancy.models import Tenant


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
            "import_id":str(item.import_batch_id), "import_code":item.import_batch.code,
            "source_date":item.import_batch.source_date.isoformat(),
            "legacy_code":item.legacy_code, "proposed_sku_code":item.proposed_sku_code,
            "source_name":item.source_name, "source_uom":item.source_uom,
            "source_cost":str(item.source_cost), "source_price":str(item.source_price),
            "source_quantity":str(item.source_quantity), "source_product":item.source_product,
            "source_stock":item.source_stock, "source_issues":item.source_issues,
            "review":item.review, "status":setup_status(item), "missing_details":missing_details(item),
            "updated_at":item.updated_at.isoformat(), "completion":item.completion, "saleable":False}


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
        if request.query_params.get("include_discarded") != "true":
            qs = qs.filter(~Q(review__has_key="discarded") | Q(review__discarded=False))
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
        imports = LegacyCatalogueImport.all_objects.filter(tenant_id=self.tenant_id(request)).annotate(item_count=Count("items", filter=~Q(items__review__discarded=True) | ~Q(items__review__has_key="discarded"))).filter(item_count__gt=0).order_by("-created_at", "id")
        return Response({"summary":summary, "count":page.paginator.count, "page":page.number,
                         "pages":page.paginator.num_pages, "can_edit":bool(self.tenant_id(request) and
                          request.user.has_capability("inventory.manage", tenant_id=self.tenant_id(request))),
                         "source_date":first.import_batch.source_date.isoformat() if first else None,
                         "imports":[{"id":str(batch.pk), "code":batch.code, "source_date":batch.source_date.isoformat(),
                                     "source_filename":batch.provenance.get("source_filename", ""), "item_count":batch.item_count} for batch in imports],
                         "results":[serialise(i) for i in page]})


class ItemUploadInput(serializers.Serializer):
    rows = serializers.ListField(child=serializers.JSONField())
    source_date = serializers.DateField()
    source_filename = serializers.CharField(max_length=255)
    dry_run = serializers.BooleanField(default=True)

    def validate_source_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("The source-data date cannot be in the future.")
        return value

    def validate_source_filename(self, value):
        if "\x00" in value:
            raise serializers.ValidationError("Remove null characters from the filename.")
        return value


class LegacyItemUpload(SetupScope):
    def post(self, request):
        tenant_id = self.tenant_id(request)
        if tenant_id is None:
            return Response({"detail":"Select an explicit tenant workspace before uploading item data."}, status=403)
        try:
            assert_setup_access(request.user, tenant_id)
        except PermissionDenied as exc:
            return Response({"detail":str(exc)}, status=403)
        payload = ItemUploadInput(data=request.data)
        payload.is_valid(raise_exception=True)
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        try:
            result = import_item_upload(tenant=tenant, actor=request.user, **payload.validated_data)
        except ValidationError as exc:
            return Response({"detail":" ".join(exc.messages)}, status=400)
        return Response(result, headers={"Cache-Control":"no-store"})


class LegacyOpeningStocktakeTemplate(SetupScope):
    renderer_classes = [JSONRenderer]

    def perform_content_negotiation(self, request, force=False):
        # The successful HttpResponse supplies its CSV content type. Accept a
        # CSV attachment request while retaining JSON for permission/API errors.
        return super().perform_content_negotiation(request, force=True)

    def get(self, request):
        tenant_id = self.tenant_id(request)
        if tenant_id is None:
            return Response({"detail":"Select an explicit tenant workspace before downloading a count sheet."}, status=403)
        try:
            assert_setup_access(request.user, tenant_id)
        except PermissionDenied as exc:
            return Response({"detail":str(exc)}, status=403)
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        items = self.scoped(request)
        import_id = request.query_params.get("import_id")
        if import_id:
            try:
                batch = get_object_or_404(LegacyCatalogueImport.all_objects, tenant=tenant, pk=import_id)
            except (ValidationError, ValueError):
                return Response({"detail":"Import not found."}, status=404)
            items = items.filter(import_batch=batch)
        content = opening_stocktake_csv(items.order_by("import_batch__created_at", "source_row", "id").iterator())
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        filename = f"tibatrace-opening-stocktake-{slugify(tenant.slug) or 'tenant'}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store"
        return response


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


class StageSetupInput(serializers.Serializer):
    expected_updated_at = serializers.CharField()
    sku_id = serializers.UUIDField(required=False, allow_null=True)
    branch_id = serializers.UUIDField()
    quarantine_location_id = serializers.UUIDField()
    product_match_confirmed = serializers.BooleanField()
    unit_match_confirmed = serializers.BooleanField()
    tax_inclusive = serializers.BooleanField()
    storage_requirement = serializers.ChoiceField(choices=["AMBIENT", "COLD_CHAIN"])
    reason = serializers.CharField(max_length=2000, allow_blank=False)


class LegacyItemStage(SetupScope):
    def post(self, request, pk):
        item = get_object_or_404(self.scoped(request), pk=pk)
        payload = StageSetupInput(data=request.data)
        payload.is_valid(raise_exception=True)
        values = dict(payload.validated_data)
        expected = values.pop("expected_updated_at")
        try:
            item = stage_opening_setup(item=item, actor=request.user, expected_updated_at=expected, values=values)
        except StaleSetupReview as exc:
            return Response({"detail":str(exc)}, status=409)
        except PermissionDenied as exc:
            return Response({"detail":str(exc)}, status=403)
        except ValidationError as exc:
            return Response({"detail":" ".join(exc.messages)}, status=400)
        return Response(serialise(item))


class ReleaseSetupInput(serializers.Serializer):
    expected_updated_at = serializers.CharField()
    destination_location_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=2000, allow_blank=False)


class LegacyItemRelease(SetupScope):
    def post(self, request, pk):
        item = get_object_or_404(self.scoped(request), pk=pk)
        payload = ReleaseSetupInput(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            item = release_opening_setup(item=item, actor=request.user, **payload.validated_data)
        except StaleSetupReview as exc:
            return Response({"detail":str(exc)}, status=409)
        except PermissionDenied as exc:
            return Response({"detail":str(exc)}, status=403)
        except ValidationError as exc:
            return Response({"detail":" ".join(exc.messages)}, status=400)
        return Response(serialise(item))


class LegacyOpeningCountUpload(SetupScope):
    def post(self, request):
        from apps.medicines.onboarding_counts import import_opening_counts
        class CountsInput(serializers.Serializer):
            rows = serializers.ListField(child=serializers.DictField(), min_length=1, max_length=5000)
            dry_run = serializers.BooleanField(default=True)
        payload = CountsInput(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            result = import_opening_counts(tenant_id=self.tenant_id(request), actor=request.user, **payload.validated_data)
        except PermissionDenied as exc:
            return Response({'detail': str(exc)}, status=403)
        except StaleSetupReview as exc:
            return Response({'detail': str(exc)}, status=409)
        except ValidationError as exc:
            return Response({'detail': ' '.join(exc.messages)}, status=400)
        return Response(result)


class LegacyImportDiscard(SetupScope):
    def post(self, request, pk):
        from django.db import transaction

        from apps.medicines.onboarding_discard import discard_import
        class Input(serializers.Serializer):
            reason = serializers.CharField(max_length=2000)
            expected_items = serializers.IntegerField(min_value=1)
        data = Input(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                batch = get_object_or_404(LegacyCatalogueImport.all_objects, pk=pk, tenant_id=self.tenant_id(request))
                result = discard_import(batch=batch, actor=request.user, **data.validated_data)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=400)
        return Response(result)
