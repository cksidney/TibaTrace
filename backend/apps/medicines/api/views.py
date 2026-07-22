from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.medicines.api.serializers import (
    ActiveSubstanceSerializer,
    AdministrationRouteSerializer,
    BranchAssortmentSerializer,
    ClinicalMedicinalProductSerializer,
    CommercialSKUSerializer,
    DoseFormSerializer,
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
    TherapeuticClassification,
)
from apps.medicines.services import MedicineCatalogueService


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


class ManufacturerViewSet(viewsets.ModelViewSet):
    queryset = Manufacturer.objects.all()
    serializer_class = ManufacturerSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "legal_name", "trading_name"]


class TherapeuticClassificationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TherapeuticClassification.objects.all()
    serializer_class = TherapeuticClassificationSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["system", "code", "display"]


class ActiveSubstanceViewSet(viewsets.ModelViewSet):
    queryset = ActiveSubstance.objects.all()
    serializer_class = ActiveSubstanceSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "canonical_name", "display_name", "search_name"]


class ClinicalMedicinalProductViewSet(viewsets.ModelViewSet):
    queryset = ClinicalMedicinalProduct.objects.all().prefetch_related("ingredients", "routes")
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


class IngredientCompositionViewSet(viewsets.ModelViewSet):
    queryset = IngredientComposition.objects.all().select_related("active_substance")
    serializer_class = IngredientCompositionSerializer


class ManufacturedMedicinalProductViewSet(viewsets.ModelViewSet):
    queryset = ManufacturedMedicinalProduct.objects.all().select_related("clinical_product", "manufacturer")
    serializer_class = ManufacturedMedicinalProductSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "brand_name", "clinical_product__canonical_name"]


class PackageDefinitionViewSet(viewsets.ModelViewSet):
    queryset = PackageDefinition.objects.all()
    serializer_class = PackageDefinitionSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "description"]


class CommercialSKUViewSet(viewsets.ModelViewSet):
    queryset = CommercialSKU.objects.all().select_related("manufactured_product", "package_definition")
    serializer_class = CommercialSKUSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["sku_code", "display_name", "default_barcode", "manufactured_product__brand_name"]

    @action(detail=False, methods=["get"], url_path="lookup")
    def lookup(self, request):
        barcode = request.query_params.get("barcode", "").strip()
        sku_code = request.query_params.get("sku_code", "").strip()

        if barcode:
            sku = CommercialSKU.objects.filter(default_barcode=barcode).first()
            if not sku:
                pid = ProductIdentifier.objects.filter(system="BARCODE", value=barcode, entity_type="SKU").first()
                if pid:
                    tenant_id = get_current_tenant_id() or getattr(request, "tenant_id", None)
                    sku = CommercialSKU.objects.filter(tenant_id=tenant_id, id=pid.entity_id).first()
        elif sku_code:
            sku = CommercialSKU.objects.filter(sku_code=sku_code).first()
        else:
            return Response({"error": "Query parameter 'barcode' or 'sku_code' is required."}, status=status.HTTP_400_BAD_REQUEST)

        if not sku:
            return Response({"error": "SKU not found for specified barcode or code."}, status=status.HTTP_404_NOT_FOUND)

        return Response(CommercialSKUSerializer(sku).data, status=status.HTTP_200_OK)


class ProductIdentifierViewSet(viewsets.ModelViewSet):
    queryset = ProductIdentifier.objects.all()
    serializer_class = ProductIdentifierSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["system", "value", "entity_type"]


class SubstitutionGroupViewSet(viewsets.ModelViewSet):
    queryset = SubstitutionGroup.objects.all()
    serializer_class = SubstitutionGroupSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "name"]


class SubstitutionPolicyViewSet(viewsets.ModelViewSet):
    queryset = SubstitutionPolicy.objects.all()
    serializer_class = SubstitutionPolicySerializer


class BranchAssortmentViewSet(viewsets.ModelViewSet):
    queryset = BranchAssortment.objects.all().select_related("sku", "location")
    serializer_class = BranchAssortmentSerializer


# Legacy Compatibility ViewSet
class MedicineViewSet(viewsets.ModelViewSet):
    queryset = Medicine.objects.all().prefetch_related("identifiers")
    serializer_class = MedicineSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "generic_name", "brand_name", "gtin", "primary_barcode"]
