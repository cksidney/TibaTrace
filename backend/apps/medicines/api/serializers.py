from rest_framework import serializers

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
    MedicineIdentifier,
    PackageDefinition,
    ProductIdentifier,
    SubstitutionGroup,
    SubstitutionPolicy,
    TherapeuticClassification,
)


class DoseFormSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoseForm
        fields = ("id", "code", "name", "description", "is_active", "created_at", "updated_at")


class AdministrationRouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdministrationRoute
        fields = ("id", "code", "name", "description", "is_active", "created_at", "updated_at")


class ManufacturerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Manufacturer
        fields = (
            "id",
            "tenant",
            "is_global",
            "code",
            "legal_name",
            "trading_name",
            "country",
            "regulator_identifier",
            "is_active",
            "created_at",
            "updated_at",
        )


class TherapeuticClassificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TherapeuticClassification
        fields = ("id", "system", "code", "display", "parent", "hierarchy_depth", "created_at", "updated_at")


class ActiveSubstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActiveSubstance
        fields = (
            "id",
            "tenant",
            "is_global",
            "code",
            "canonical_name",
            "display_name",
            "search_name",
            "substance_type",
            "controlled_classification",
            "status",
            "created_at",
            "updated_at",
        )


class IngredientCompositionSerializer(serializers.ModelSerializer):
    active_substance_name = serializers.ReadOnlyField(source="active_substance.canonical_name")

    class Meta:
        model = IngredientComposition
        fields = (
            "id",
            "clinical_product",
            "active_substance",
            "active_substance_name",
            "numerator_value",
            "numerator_unit",
            "denominator_value",
            "denominator_unit",
            "role",
            "sequence",
            "basis_of_strength",
            "is_exact",
        )


class ClinicalMedicinalProductSerializer(serializers.ModelSerializer):
    ingredients = IngredientCompositionSerializer(many=True, read_only=True)
    dose_form_name = serializers.ReadOnlyField(source="dose_form.name")

    class Meta:
        model = ClinicalMedicinalProduct
        fields = (
            "id",
            "tenant",
            "is_global",
            "code",
            "canonical_name",
            "dose_form",
            "dose_form_name",
            "routes",
            "prescription_classification",
            "controlled_classification",
            "antimicrobial_classification",
            "therapeutic_classifications",
            "paediatric_suitable",
            "cautions_summary",
            "status",
            "ingredients",
            "created_at",
            "updated_at",
        )


class ManufacturedMedicinalProductSerializer(serializers.ModelSerializer):
    clinical_product_name = serializers.ReadOnlyField(source="clinical_product.canonical_name")
    manufacturer_name = serializers.ReadOnlyField(source="manufacturer.legal_name", default="")

    class Meta:
        model = ManufacturedMedicinalProduct
        fields = (
            "id",
            "tenant",
            "is_global",
            "code",
            "brand_name",
            "clinical_product",
            "clinical_product_name",
            "manufacturer",
            "manufacturer_name",
            "market_authorisation_number",
            "licence_status",
            "status",
            "created_at",
            "updated_at",
        )


class PackageDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackageDefinition
        fields = (
            "id",
            "code",
            "description",
            "parent_package",
            "quantity_in_parent",
            "unit_of_measure",
            "pack_level",
            "is_dispensing_unit",
            "is_procurement_unit",
            "is_sales_unit",
            "is_active",
            "created_at",
            "updated_at",
        )


class CommercialSKUSerializer(serializers.ModelSerializer):
    sales_unit = serializers.ReadOnlyField(source="package_definition.unit_of_measure")
    package_description = serializers.ReadOnlyField(source="package_definition.description")
    brand_name = serializers.ReadOnlyField(source="manufactured_product.brand_name")
    canonical_medicine_name = serializers.ReadOnlyField(
        source="manufactured_product.clinical_product.canonical_name"
    )

    class Meta:
        model = CommercialSKU
        fields = (
            "id",
            "tenant",
            "sku_code",
            "display_name",
            "manufactured_product",
            "brand_name",
            "canonical_medicine_name",
            "package_definition",
            "sales_unit",
            "package_description",
            "default_barcode",
            "tax_category",
            "stock_tracking_required",
            "batch_tracking_required",
            "expiry_tracking_required",
            "is_saleable",
            "is_purchasable",
            "is_dispensable",
            "status",
            "created_at",
            "updated_at",
        )


class CatalogueIntakeSerializer(serializers.Serializer):
    clinical_code = serializers.CharField(max_length=100)
    canonical_name = serializers.CharField(max_length=255)
    dose_form_id = serializers.UUIDField()
    active_substance_id = serializers.UUIDField()
    strength_value = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0)
    strength_unit = serializers.CharField(max_length=50)
    manufactured_code = serializers.CharField(max_length=100)
    brand_name = serializers.CharField(max_length=255)
    manufacturer_id = serializers.UUIDField(required=False, allow_null=True)
    market_authorisation_number = serializers.CharField(max_length=150, required=False, allow_blank=True)
    sku_code = serializers.CharField(max_length=100)
    display_name = serializers.CharField(max_length=255)
    package_definition_id = serializers.UUIDField()
    default_barcode = serializers.CharField(max_length=100, required=False, allow_blank=True)
    tax_category = serializers.CharField(max_length=80, default="STANDARD")

    def validate(self, attrs):
        for field in ("clinical_code", "canonical_name", "strength_unit", "manufactured_code", "brand_name", "sku_code", "display_name"):
            attrs[field] = attrs[field].strip()
            if not attrs[field]:
                raise serializers.ValidationError({field: "This field cannot be blank."})
        attrs["clinical_code"] = attrs["clinical_code"].upper()
        attrs["manufactured_code"] = attrs["manufactured_code"].upper()
        attrs["sku_code"] = attrs["sku_code"].upper()
        if attrs["strength_value"] <= 0:
            raise serializers.ValidationError({"strength_value": "Strength must be greater than zero."})
        return attrs


class ProductIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductIdentifier
        fields = (
            "id",
            "entity_type",
            "entity_id",
            "system",
            "value",
            "issuing_authority",
            "is_primary",
            "is_verified",
            "created_at",
            "updated_at",
        )


class SubstitutionGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubstitutionGroup
        fields = ("id", "code", "name", "description", "clinical_products", "is_active", "created_at", "updated_at")


class SubstitutionPolicySerializer(serializers.ModelSerializer):
    group_name = serializers.ReadOnlyField(source="substitution_group.name")

    class Meta:
        model = SubstitutionPolicy
        fields = (
            "id",
            "tenant",
            "substitution_group",
            "group_name",
            "policy_type",
            "approval_required",
            "reason_required",
            "is_active",
            "created_at",
            "updated_at",
        )


class BranchAssortmentSerializer(serializers.ModelSerializer):
    sku_name = serializers.ReadOnlyField(source="sku.display_name")

    class Meta:
        model = BranchAssortment
        fields = (
            "id",
            "tenant",
            "location",
            "sku",
            "sku_name",
            "is_sellable",
            "is_purchasable",
            "is_dispensable",
            "is_stocked",
            "formulary_status",
            "created_at",
            "updated_at",
        )


# Legacy Compatibility Serializer
class MedicineIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicineIdentifier
        fields = ("id", "system", "value")


class MedicineSerializer(serializers.ModelSerializer):
    identifiers = MedicineIdentifierSerializer(many=True, read_only=True)

    class Meta:
        model = Medicine
        fields = (
            "id",
            "tenant",
            "is_global",
            "code",
            "generic_name",
            "brand_name",
            "dosage_form",
            "strength",
            "gtin",
            "primary_barcode",
            "atc_code",
            "status",
            "source",
            "source_version",
            "licence_identifier",
            "metadata",
            "identifiers",
            "created_at",
            "updated_at",
        )


class GovernmentCatalogueMedicineSerializer(serializers.ModelSerializer):
    catalogue_standard = serializers.SerializerMethodField()
    keml_status = serializers.SerializerMethodField()
    level_of_use = serializers.SerializerMethodField()
    manufacturer_name = serializers.SerializerMethodField()
    route = serializers.SerializerMethodField()
    source_updated_at = serializers.SerializerMethodField()
    selected = serializers.SerializerMethodField()
    selection_status = serializers.SerializerMethodField()
    tenant_code = serializers.SerializerMethodField()

    class Meta:
        model = Medicine
        fields = (
            "id",
            "code",
            "generic_name",
            "brand_name",
            "dosage_form",
            "strength",
            "route",
            "licence_identifier",
            "manufacturer_name",
            "keml_status",
            "level_of_use",
            "status",
            "catalogue_standard",
            "source_updated_at",
            "selected",
            "selection_status",
            "tenant_code",
        )

    def get_catalogue_standard(self, medicine):
        return medicine.metadata.get("catalogue_standard", "")

    def get_keml_status(self, medicine):
        return medicine.metadata.get("keml", {}).get("status", "UNKNOWN")

    def get_level_of_use(self, medicine):
        return medicine.metadata.get("keml", {}).get("level_of_use", "")

    def get_manufacturer_name(self, medicine):
        return medicine.metadata.get("manufacturer_name", "")

    def get_route(self, medicine):
        return medicine.metadata.get("route", {}).get("display_name", "")

    def get_source_updated_at(self, medicine):
        return medicine.metadata.get("source_updated_at", "")

    def get_selected(self, medicine):
        selection = self._selection(medicine)
        return bool(selection and selection.status == "SELECTED")

    def get_selection_status(self, medicine):
        selection = self._selection(medicine)
        return selection.status if selection else ""

    def get_tenant_code(self, medicine):
        selection = self._selection(medicine)
        return selection.tenant_code if selection else ""

    def _selection(self, medicine):
        return self.context.get("selections", {}).get(str(medicine.pk))
