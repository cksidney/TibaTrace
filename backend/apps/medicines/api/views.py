from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.tenant_context import get_current_tenant_id
from apps.medicines.api.serializers import (
    ActiveSubstanceSerializer,
    AdministrationRouteSerializer,
    BranchAssortmentSerializer,
    CatalogueIntakeSerializer,
    ClinicalMedicinalProductSerializer,
    CommercialSKUSerializer,
    DoseFormSerializer,
    GovernmentCatalogueMedicineSerializer,
    IngredientCompositionSerializer,
    ManufacturedMedicinalProductSerializer,
    ManufacturerSerializer,
    MedicineSerializer,
    PackageDefinitionSerializer,
    ProductIdentifierSerializer,
    SubstitutionGroupSerializer,
    SubstitutionPolicySerializer,
    TherapeuticClassificationSerializer,
)
from apps.medicines.government_catalogue import KEML_STATUSES, LEVELS_OF_USE, SOURCE_NAME
from apps.medicines.models import (
    ActiveSubstance,
    AdministrationRoute,
    BranchAssortment,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    IngredientComposition,
    ManufacturedMedicinalProduct,
    Manufacturer,
    Medicine,
    PackageDefinition,
    ProductIdentifier,
    SubstitutionGroup,
    SubstitutionPolicy,
    TenantCatalogueProduct,
    TherapeuticClassification,
)
from apps.medicines.services import (
    BranchAssortmentService,
    BulkTenantCatalogueSelectionService,
    MedicineCatalogueService,
    TenantCatalogueService,
)
from apps.tenancy.models import Tenant

# Every viewset here is read-only.
#
# They were ModelViewSets, so the product master -- the table every dispensing
# decision resolves against -- took POST, PATCH and DELETE from any
# authenticated caller, with no service, no approval and no audit. Nothing in
# the repository wrote through them: the government-catalogue selection endpoint
# is a separate view, and the HQ catalogue screens only read.
#
# Governed creation already exists in MedicineCatalogueService
# (create_clinical_product, register_manufactured_product, register_sku,
# activate_clinical_product) and is the path a write should take when a UI needs
# one -- exposed as a service action, the way procurement does it, rather than
# by re-opening a generic write that bypasses the service entirely.


class TenantScopedQuerysetMixin:
    """Build the queryset per request, from the model, with an explicit filter.

    These viewsets declared `queryset = Model.objects.all()` as a class
    attribute. That is evaluated once at import, when there is definitively no
    tenant context, so the tenant-strict manager returned `.none()`. DRF clones
    that queryset per request rather than re-consulting the manager, so it
    stayed empty for the life of the process -- every medicines endpoint
    returned nothing, for every caller, whatever they authenticated as.

    Building it per request fixes that. It also moves the isolation onto a line
    you can read: an explicit `filter(tenant_id=...)` rather than a thread-local
    the manager consults, set by middleware that happens to run earlier. The
    strict manager does fail closed, so the implicit version was not a leak --
    but its failure mode is a silently empty result, which reads as missing data
    rather than as a bug, and has cost this repository five debugging sessions.

    Subclasses set `model`. Global reference data -- dose forms, routes, package
    definitions, product identifiers -- has no tenant column and does not use
    this; `objects` on those is an ordinary manager.
    """

    model = None
    #: Relations to pull in the same query. Declared rather than chained onto a
    #: class-level queryset, which is what froze these viewsets empty.
    select_related: list[str] = []
    prefetch_related: list[str] = []

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
            # No tenant, no rows. An unscoped read here would expose one
            # pharmacy's catalogue to another.
            return self.model.all_objects.none()

        queryset = self.model.all_objects.filter(tenant_id=tenant_id)
        if self.select_related:
            queryset = queryset.select_related(*self.select_related)
        if self.prefetch_related:
            queryset = queryset.prefetch_related(*self.prefetch_related)
        return queryset


class DoseFormViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DoseForm.objects.all()
    serializer_class = DoseFormSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "name"]


class AdministrationRouteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AdministrationRoute.objects.all()
    serializer_class = AdministrationRouteSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "name"]


class ManufacturerViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = Manufacturer
    serializer_class = ManufacturerSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "legal_name", "trading_name"]

    def get_queryset(self):
        tenant_id = self.tenant_id()
        if tenant_id is None:
            return Manufacturer.all_objects.none()
        return Manufacturer.all_objects.filter(
            Q(tenant_id=tenant_id) | Q(tenant__isnull=True, is_global=True)
        )


class TherapeuticClassificationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TherapeuticClassification.objects.all()
    serializer_class = TherapeuticClassificationSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["system", "code", "display"]


class ActiveSubstanceViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = ActiveSubstance
    serializer_class = ActiveSubstanceSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "canonical_name", "display_name", "search_name"]

    def get_queryset(self):
        tenant_id = self.tenant_id()
        if tenant_id is None:
            return ActiveSubstance.all_objects.none()
        return ActiveSubstance.all_objects.filter(
            Q(tenant_id=tenant_id) | Q(tenant__isnull=True, is_global=True)
        )


class ClinicalMedicinalProductViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = ClinicalMedicinalProduct
    # Every relation the serializer touches. `dose_form_name` reads through the
    # FK, and each ingredient reads its active substance, so omitting either
    # costs a query per row -- which is what this list was doing once it started
    # returning rows at all.
    select_related = ["dose_form"]
    prefetch_related = [
        "routes",
        "therapeutic_classifications",
        "ingredients__active_substance",
    ]
    serializer_class = ClinicalMedicinalProductSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "canonical_name"]

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        product = self.get_object()
        activated = MedicineCatalogueService.activate_clinical_product(
            product=product, actor=request.user if request.user.is_authenticated else None
        )
        return Response(ClinicalMedicinalProductSerializer(activated).data, status=status.HTTP_200_OK)


class IngredientCompositionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = IngredientComposition.objects.all().select_related("active_substance")
    serializer_class = IngredientCompositionSerializer


class ManufacturedMedicinalProductViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = ManufacturedMedicinalProduct
    select_related = ["clinical_product", "manufacturer"]
    serializer_class = ManufacturedMedicinalProductSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "brand_name", "clinical_product__canonical_name"]


class PackageDefinitionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PackageDefinition.objects.all()
    serializer_class = PackageDefinitionSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "description"]


class CommercialSKUViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = CommercialSKU
    # `canonical_medicine_name` reads two FKs deep, through the manufactured
    # product to its clinical product.
    select_related = [
        "manufactured_product__clinical_product",
        "package_definition",
    ]
    serializer_class = CommercialSKUSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["sku_code", "display_name", "default_barcode", "manufactured_product__brand_name"]

    @action(detail=False, methods=["post"], url_path="intake")
    def intake(self, request):
        """Create a complete tenant product chain in DRAFT for review."""
        tenant_id = self.tenant_id()
        if not tenant_id or not request.user.has_capability("catalogue.manage", tenant_id=tenant_id):
            raise PermissionDenied("Catalogue authoring requires the catalogue.manage capability.")
        payload = CatalogueIntakeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        values = payload.validated_data

        tenant = get_object_or_404(Tenant, pk=tenant_id)
        dose_form = get_object_or_404(DoseForm.objects.filter(is_active=True), pk=values["dose_form_id"])
        # Bound reference visibility before resolving the submitted identifier.
        substance = ActiveSubstance.all_objects.filter(
            Q(tenant_id=tenant_id) | Q(tenant__isnull=True, is_global=True)
        ).filter(pk=values["active_substance_id"], status="ACTIVE").first()
        if substance is None:
            raise serializers.ValidationError({"active_substance_id": "Select an active ingredient available to this tenant."})
        package = get_object_or_404(PackageDefinition.objects.filter(is_active=True), pk=values["package_definition_id"])
        manufacturer = None
        if values.get("manufacturer_id"):
            manufacturer = Manufacturer.all_objects.filter(
                Q(tenant_id=tenant_id) | Q(tenant__isnull=True, is_global=True)
            ).filter(pk=values["manufacturer_id"]).first()
            if manufacturer is None:
                raise serializers.ValidationError({"manufacturer_id": "Select a manufacturer available to this tenant."})

        from apps.medicines.services import MedicineCatalogueService

        try:
            with transaction.atomic():
                sku = MedicineCatalogueService.create_tenant_sku(
                    tenant=tenant,
                    clinical_code=values["clinical_code"],
                    canonical_name=values["canonical_name"],
                    dose_form=dose_form,
                    active_substance=substance,
                    strength_value=values["strength_value"],
                    strength_unit=values["strength_unit"],
                    manufactured_code=values["manufactured_code"],
                    brand_name=values["brand_name"],
                    manufacturer=manufacturer,
                    market_authorisation_number=values.get("market_authorisation_number", ""),
                    sku_code=values["sku_code"],
                    display_name=values["display_name"],
                    package_definition=package,
                    default_barcode=values.get("default_barcode", ""),
                    tax_category=values["tax_category"],
                    actor=request.user,
                )
        except IntegrityError as exc:
            raise serializers.ValidationError({"sku_code": "A clinical, manufactured or SKU code already exists."}) from exc
        return Response(self.get_serializer(sku).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="lookup")
    def lookup(self, request):
        barcode = request.query_params.get("barcode", "").strip()
        sku_code = request.query_params.get("sku_code", "").strip()

        # Every lookup is filtered by tenant explicitly. A barcode scan that
        # resolved across tenants would put another pharmacy's product on this
        # till, which is the one thing a scan must never do.
        tenant_id = self.tenant_id()
        if tenant_id is None:
            return Response(
                {"error": "No workspace is associated with this request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if barcode:
            sku = CommercialSKU.all_objects.filter(
                tenant_id=tenant_id, default_barcode=barcode
            ).first()
            if not sku:
                # ProductIdentifier is global reference data with no tenant
                # column. The isolation is the SKU filter below: an identifier
                # belonging to another tenant's SKU resolves to nothing here.
                pid = ProductIdentifier.objects.filter(
                    system="BARCODE", value=barcode, entity_type="SKU"
                ).first()
                if pid:
                    sku = CommercialSKU.all_objects.filter(
                        tenant_id=tenant_id, id=pid.entity_id
                    ).first()
        elif sku_code:
            sku = CommercialSKU.all_objects.filter(
                tenant_id=tenant_id, sku_code=sku_code
            ).first()
        else:
            return Response({"error": "Query parameter 'barcode' or 'sku_code' is required."}, status=status.HTTP_400_BAD_REQUEST)

        if not sku:
            return Response({"error": "SKU not found for specified barcode or code."}, status=status.HTTP_404_NOT_FOUND)

        return Response(CommercialSKUSerializer(sku).data, status=status.HTTP_200_OK)


class ProductIdentifierViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductIdentifier.objects.all()
    serializer_class = ProductIdentifierSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["system", "value", "entity_type"]


class SubstitutionGroupViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SubstitutionGroup.objects.all()
    serializer_class = SubstitutionGroupSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "name"]


class SubstitutionPolicyViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = SubstitutionPolicy
    serializer_class = SubstitutionPolicySerializer


class BranchAssortmentViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = BranchAssortment
    select_related = ["sku", "location"]
    serializer_class = BranchAssortmentSerializer

    @action(detail=False, methods=["post"], url_path="provision")
    def provision(self, request):
        from apps.organizations.models import Location

        tenant_id = self.tenant_id()
        if not tenant_id or not request.user.has_capability("catalogue.manage", tenant_id=tenant_id):
            raise PermissionDenied("Branch assortment authoring requires catalogue.manage.")
        try:
            from uuid import UUID
            branch_id = UUID(str(request.data.get("branch_id", "")))
            sku_id = UUID(str(request.data.get("sku_id", "")))
        except ValueError:
            raise serializers.ValidationError("Select a valid branch and SKU.")
        branch = get_object_or_404(Location.all_objects.filter(tenant_id=tenant_id, status="ACTIVE", organization__status="ACTIVE"), pk=branch_id)
        sku = get_object_or_404(CommercialSKU.all_objects.filter(tenant_id=tenant_id, status="ACTIVE", manufactured_product__clinical_product__status="ACTIVE"), pk=sku_id)
        assortment = BranchAssortmentService.enable_sku_for_branch(tenant=branch.tenant, location=branch, sku=sku, actor=request.user)
        return Response(self.get_serializer(assortment).data)


# Legacy Compatibility ViewSet
class MedicineViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = Medicine
    prefetch_related = ["identifiers"]
    serializer_class = MedicineSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "generic_name", "brand_name", "gtin", "primary_barcode"]


class GovernmentCatalogueView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = self._tenant(request)
        base_queryset = Medicine.all_objects.filter(
            tenant__isnull=True,
            is_global=True,
            source=SOURCE_NAME,
        )
        catalogue_count = base_queryset.count()
        source_version = (
            base_queryset.order_by("-updated_at")
            .values_list("source_version", flat=True)
            .first()
            or ""
        )

        queryset = base_queryset
        query = request.query_params.get("q", "").strip()[:200]
        if query:
            queryset = queryset.filter(
                Q(code__icontains=query)
                | Q(generic_name__icontains=query)
                | Q(brand_name__icontains=query)
                | Q(dosage_form__icontains=query)
                | Q(strength__icontains=query)
                | Q(licence_identifier__icontains=query)
                | Q(metadata__manufacturer_name__icontains=query)
                | Q(metadata__route__display_name__icontains=query)
            )

        keml_status = request.query_params.get("keml_status", "").strip()
        if keml_status in KEML_STATUSES:
            queryset = queryset.filter(metadata__keml__status=keml_status)

        level_of_use = request.query_params.get("level_of_use", "").strip()
        if level_of_use in LEVELS_OF_USE:
            queryset = queryset.filter(metadata__keml__level_of_use=level_of_use)

        selected_count = 0
        if tenant is not None:
            selected_queryset = TenantCatalogueProduct.all_objects.filter(
                tenant=tenant,
                status=TenantCatalogueProduct.STATUS_SELECTED,
            )
            selected_count = selected_queryset.count()
            if request.query_params.get("selected_only", "").lower() in {
                "1",
                "true",
                "yes",
            }:
                queryset = queryset.filter(
                    tenant_catalogue_products__tenant=tenant,
                    tenant_catalogue_products__status=TenantCatalogueProduct.STATUS_SELECTED,
                )

        page_size = self._bounded_integer(
            request.query_params.get("page_size"),
            default=50,
            minimum=10,
            maximum=100,
        )
        paginator = Paginator(
            queryset.order_by("generic_name", "brand_name", "code"),
            page_size,
        )
        page = paginator.get_page(request.query_params.get("page", "1"))
        selections = {}
        if tenant is not None:
            selections = {
                str(selection.master_medicine_id): selection
                for selection in TenantCatalogueProduct.all_objects.filter(
                    tenant=tenant,
                    master_medicine_id__in=[
                        medicine.pk for medicine in page.object_list
                    ],
                )
            }
        serializer = GovernmentCatalogueMedicineSerializer(
            page.object_list,
            many=True,
            context={"selections": selections},
        )

        return Response(
            {
                "source": SOURCE_NAME,
                "source_version": source_version,
                "catalogue_count": catalogue_count,
                "count": paginator.count,
                "page": page.number,
                "page_size": page_size,
                "pages": paginator.num_pages,
                "tenant_id": str(tenant.pk) if tenant else "",
                "tenant_name": tenant.name if tenant else "",
                "selected_count": selected_count,
                "can_manage": self._can_manage(request, tenant),
                "available_keml_statuses": sorted(KEML_STATUSES),
                "available_levels_of_use": sorted(LEVELS_OF_USE, key=int),
                "results": serializer.data,
            }
        )

    @staticmethod
    def _bounded_integer(value, *, default, minimum, maximum):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(parsed, maximum))

    @staticmethod
    def _tenant(request):
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        if not tenant_id:
            return None
        return Tenant.objects.filter(pk=tenant_id, status=Tenant.STATUS_ACTIVE).first()

    @staticmethod
    def _can_manage(request, tenant):
        if tenant is None:
            return False
        return bool(
            request.user.is_superuser
            or request.user.is_platform_admin
            or request.user.has_capability(
                "catalogue.manage",
                tenant_id=tenant.pk,
            )
        )


class GovernmentCatalogueSelectionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        tenant = GovernmentCatalogueView._tenant(request)
        permission_error = self._permission_error(request, tenant)
        if permission_error:
            return permission_error
        medicine = get_object_or_404(
            Medicine.all_objects,
            pk=pk,
            tenant__isnull=True,
            is_global=True,
            source=SOURCE_NAME,
        )
        try:
            selection, created = TenantCatalogueService.select_master_product(
                tenant=tenant,
                master_medicine=medicine,
                actor=request.user,
            )
        except ValidationError as exc:
            return Response(
                {"detail": " ".join(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "selected": True,
                "selection_id": str(selection.pk),
                "tenant_id": str(tenant.pk),
                "master_medicine_id": str(medicine.pk),
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        tenant = GovernmentCatalogueView._tenant(request)
        permission_error = self._permission_error(request, tenant)
        if permission_error:
            return permission_error
        selection = get_object_or_404(
            TenantCatalogueProduct.all_objects.select_related("master_medicine", "tenant"),
            tenant=tenant,
            master_medicine_id=pk,
            status=TenantCatalogueProduct.STATUS_SELECTED,
        )
        TenantCatalogueService.remove_master_product(
            selection=selection,
            actor=request.user,
        )
        return Response(
            {
                "selected": False,
                "selection_id": str(selection.pk),
                "tenant_id": str(tenant.pk),
                "master_medicine_id": str(pk),
            }
        )

    @staticmethod
    def _permission_error(request, tenant):
        if tenant is None:
            return Response(
                {"detail": "Select an active tenant workspace first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not GovernmentCatalogueView._can_manage(request, tenant):
            return Response(
                {"detail": "Catalogue management permission is required."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None


class GovernmentCatalogueBulkSelectionView(APIView):
    """Preview or atomically select many universal catalogue products.

    CSV parsing happens in HQ so no spreadsheet needs to be stored server-side.
    This boundary receives only the exact master codes and still repeats all
    authoritative checks before it writes a tenant selection.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant = GovernmentCatalogueView._tenant(request)
        permission_error = GovernmentCatalogueSelectionView._permission_error(request, tenant)
        if permission_error:
            return permission_error

        dry_run = request.data.get("dry_run", True)
        if not isinstance(dry_run, bool):
            return Response(
                {"detail": "dry_run must be true or false."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = BulkTenantCatalogueSelectionService.import_rows(
            tenant=tenant,
            rows=request.data.get("rows"),
            actor=request.user,
            dry_run=dry_run,
        )
        # A preview is a validation report, not a malformed request.  Returning
        # it as 200 lets HQ show every fixable spreadsheet row at once.  An
        # attempted write with the same errors is still refused as 400.
        if result["errors"]:
            return Response(
                result,
                status=status.HTTP_200_OK if dry_run else status.HTTP_400_BAD_REQUEST,
            )
        return Response(result, status=status.HTTP_200_OK)
