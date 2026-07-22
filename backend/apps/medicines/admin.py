from django.contrib import admin

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


@admin.register(DoseForm)
class DoseFormAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


@admin.register(AdministrationRoute)
class AdministrationRouteAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ("code", "legal_name", "country", "is_global", "is_active")
    search_fields = ("code", "legal_name", "trading_name")


@admin.register(TherapeuticClassification)
class TherapeuticClassificationAdmin(admin.ModelAdmin):
    list_display = ("system", "code", "display", "parent", "hierarchy_depth")
    search_fields = ("system", "code", "display")


@admin.register(ActiveSubstance)
class ActiveSubstanceAdmin(admin.ModelAdmin):
    list_display = ("code", "canonical_name", "substance_type", "controlled_classification", "status")
    search_fields = ("code", "canonical_name", "search_name")


class IngredientCompositionInline(admin.TabularInline):
    model = IngredientComposition
    extra = 1


@admin.register(ClinicalMedicinalProduct)
class ClinicalMedicinalProductAdmin(admin.ModelAdmin):
    list_display = ("code", "canonical_name", "dose_form", "prescription_classification", "status")
    search_fields = ("code", "canonical_name")
    inlines = [IngredientCompositionInline]


@admin.register(ManufacturedMedicinalProduct)
class ManufacturedMedicinalProductAdmin(admin.ModelAdmin):
    list_display = ("code", "brand_name", "clinical_product", "manufacturer", "status")
    search_fields = ("code", "brand_name")


@admin.register(PackageDefinition)
class PackageDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "description", "unit_of_measure", "pack_level", "is_active")
    search_fields = ("code", "description")


@admin.register(CommercialSKU)
class CommercialSKUAdmin(admin.ModelAdmin):
    list_display = ("sku_code", "display_name", "manufactured_product", "default_barcode", "status")
    search_fields = ("sku_code", "display_name", "default_barcode")


@admin.register(ProductIdentifier)
class ProductIdentifierAdmin(admin.ModelAdmin):
    list_display = ("system", "value", "entity_type", "is_primary", "is_verified")
    search_fields = ("system", "value")


@admin.register(SubstitutionGroup)
class SubstitutionGroupAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


@admin.register(SubstitutionPolicy)
class SubstitutionPolicyAdmin(admin.ModelAdmin):
    list_display = ("tenant", "substitution_group", "policy_type", "approval_required", "is_active")


@admin.register(BranchAssortment)
class BranchAssortmentAdmin(admin.ModelAdmin):
    list_display = ("tenant", "location", "sku", "is_sellable", "is_dispensable", "is_stocked")


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ("code", "generic_name", "brand_name", "dosage_form", "strength", "status")
    search_fields = ("code", "generic_name", "brand_name")
