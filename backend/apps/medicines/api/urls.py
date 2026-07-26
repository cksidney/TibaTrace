from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.medicines.api.views import (
    ActiveSubstanceViewSet,
    AdministrationRouteViewSet,
    BranchAssortmentViewSet,
    ClinicalMedicinalProductViewSet,
    CommercialSKUViewSet,
    DoseFormViewSet,
    GovernmentCatalogueSelectionView,
    GovernmentCatalogueView,
    IngredientCompositionViewSet,
    ManufacturedMedicinalProductViewSet,
    ManufacturerViewSet,
    MedicineViewSet,
    PackageDefinitionViewSet,
    ProductIdentifierViewSet,
    SubstitutionGroupViewSet,
    SubstitutionPolicyViewSet,
    TherapeuticClassificationViewSet,
)

router = DefaultRouter()
router.register("dose-forms", DoseFormViewSet, basename="dose-forms")
router.register("routes", AdministrationRouteViewSet, basename="routes")
router.register("manufacturers", ManufacturerViewSet, basename="manufacturers")
router.register("classifications", TherapeuticClassificationViewSet, basename="classifications")
router.register("substances", ActiveSubstanceViewSet, basename="substances")
router.register("clinical-products", ClinicalMedicinalProductViewSet, basename="clinical-products")
router.register("ingredients", IngredientCompositionViewSet, basename="ingredients")
router.register("manufactured-products", ManufacturedMedicinalProductViewSet, basename="manufactured-products")
router.register("packages", PackageDefinitionViewSet, basename="packages")
router.register("skus", CommercialSKUViewSet, basename="skus")
router.register("identifiers", ProductIdentifierViewSet, basename="identifiers")
router.register("substitution-groups", SubstitutionGroupViewSet, basename="substitution-groups")
router.register("substitution-policies", SubstitutionPolicyViewSet, basename="substitution-policies")
router.register("branch-assortments", BranchAssortmentViewSet, basename="branch-assortments")
router.register("catalog", MedicineViewSet, basename="catalog")

urlpatterns = [
    path(
        "government-catalogue/",
        GovernmentCatalogueView.as_view(),
        name="government-catalogue",
    ),
    path(
        "government-catalogue/<uuid:pk>/selection/",
        GovernmentCatalogueSelectionView.as_view(),
        name="government-catalogue-selection",
    ),
    *router.urls,
]
