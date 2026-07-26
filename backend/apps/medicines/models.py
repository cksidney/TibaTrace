from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel


class DoseForm(TimestampedModel):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class AdministrationRoute(TimestampedModel):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Manufacturer(TimestampedModel):
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="manufacturers"
    )
    is_global = models.BooleanField(default=False)
    code = models.CharField(max_length=100)
    legal_name = models.CharField(max_length=255)
    trading_name = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=100, blank=True)
    regulator_identifier = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(tenant__isnull=True, is_global=True)
                    | models.Q(tenant__isnull=False, is_global=False)
                ),
                name="ck_manufacturer_scope",
            ),
            models.UniqueConstraint(
                fields=["tenant", "code"],
                condition=models.Q(tenant__isnull=False),
                name="uq_manufacturer_tenant_code",
            ),
        ]

    def __str__(self):
        return self.legal_name


class TherapeuticClassification(TimestampedModel):
    system = models.CharField(max_length=100)  # e.g., ATC
    code = models.CharField(max_length=100)
    display = models.CharField(max_length=255)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")
    hierarchy_depth = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["system", "code"], name="uq_therapeutic_classification_system_code")
        ]

    def __str__(self):
        return f"{self.display} [{self.system}:{self.code}]"


class ActiveSubstance(TimestampedModel):
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="substances"
    )
    is_global = models.BooleanField(default=False)
    code = models.CharField(max_length=100)
    canonical_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    search_name = models.CharField(max_length=255)
    substance_type = models.CharField(max_length=80, default="CHEMICAL")
    controlled_classification = models.CharField(max_length=80, default="NONE")
    status = models.CharField(max_length=30, default="ACTIVE")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(tenant__isnull=True, is_global=True)
                    | models.Q(tenant__isnull=False, is_global=False)
                ),
                name="ck_substance_scope",
            )
        ]

    def clean(self):
        super().clean()
        if not self.search_name:
            self.search_name = self.canonical_name.lower().strip()

    def __str__(self):
        return self.canonical_name


class ClinicalMedicinalProduct(TimestampedModel):
    STATUS_DRAFT = "DRAFT"
    STATUS_UNDER_REVIEW = "UNDER_REVIEW"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_SUSPENDED = "SUSPENDED"
    STATUS_RETIRED = "RETIRED"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_RETIRED, "Retired"),
    )

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="clinical_products"
    )
    is_global = models.BooleanField(default=False)
    code = models.CharField(max_length=100)
    canonical_name = models.CharField(max_length=255)
    dose_form = models.ForeignKey(DoseForm, on_delete=models.PROTECT, related_name="clinical_products")
    routes = models.ManyToManyField(AdministrationRoute, related_name="clinical_products", blank=True)
    prescription_classification = models.CharField(max_length=80, default="PRESCRIPTION_ONLY")
    controlled_classification = models.CharField(max_length=80, default="NONE")
    antimicrobial_classification = models.CharField(max_length=80, default="NONE")
    therapeutic_classifications = models.ManyToManyField(TherapeuticClassification, blank=True)
    paediatric_suitable = models.BooleanField(default=True)
    cautions_summary = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(tenant__isnull=True, is_global=True)
                    | models.Q(tenant__isnull=False, is_global=False)
                ),
                name="ck_clinical_product_scope",
            )
        ]

    def __str__(self):
        return self.canonical_name


class IngredientComposition(TimestampedModel):
    clinical_product = models.ForeignKey(
        ClinicalMedicinalProduct, on_delete=models.CASCADE, related_name="ingredients"
    )
    active_substance = models.ForeignKey(ActiveSubstance, on_delete=models.PROTECT, related_name="compositions")
    numerator_value = models.DecimalField(max_digits=14, decimal_places=4)
    numerator_unit = models.CharField(max_length=50)
    denominator_value = models.DecimalField(max_digits=14, decimal_places=4, default=1)
    denominator_unit = models.CharField(max_length=50, default="unit")
    role = models.CharField(max_length=50, default="ACTIVE")
    sequence = models.PositiveIntegerField(default=1)
    basis_of_strength = models.CharField(max_length=100, default="ACTIVE_MOIETY")
    is_exact = models.BooleanField(default=True)

    class Meta:
        ordering = ["sequence", "id"]

    def __str__(self):
        return f"{self.active_substance.canonical_name} {self.numerator_value} {self.numerator_unit}"


class ManufacturedMedicinalProduct(TimestampedModel):
    STATUS_DRAFT = "DRAFT"
    STATUS_REGISTERED = "REGISTERED"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_SUSPENDED = "SUSPENDED"
    STATUS_WITHDRAWN = "WITHDRAWN"
    STATUS_DISCONTINUED = "DISCONTINUED"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_REGISTERED, "Registered"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_WITHDRAWN, "Withdrawn"),
        (STATUS_DISCONTINUED, "Discontinued"),
    )

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="manufactured_products"
    )
    is_global = models.BooleanField(default=False)
    code = models.CharField(max_length=100)
    brand_name = models.CharField(max_length=255)
    clinical_product = models.ForeignKey(
        ClinicalMedicinalProduct, on_delete=models.PROTECT, related_name="manufactured_products"
    )
    manufacturer = models.ForeignKey(
        Manufacturer, on_delete=models.PROTECT, related_name="manufactured_products", null=True, blank=True
    )
    market_authorisation_number = models.CharField(max_length=150, blank=True)
    licence_status = models.CharField(max_length=80, default="LICENSED")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"{self.brand_name} [{self.code}]"


class PackageDefinition(TimestampedModel):
    code = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255)
    parent_package = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="child_packages"
    )
    quantity_in_parent = models.DecimalField(max_digits=12, decimal_places=4, default=1)
    unit_of_measure = models.CharField(max_length=50)
    pack_level = models.CharField(max_length=50, default="OUTER")  # BASE, INNER, OUTER, CARTON
    is_dispensing_unit = models.BooleanField(default=False)
    is_procurement_unit = models.BooleanField(default=True)
    is_sales_unit = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.description} ({self.code})"


class CommercialSKU(TimestampedModel):
    STATUS_DRAFT = "DRAFT"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_INACTIVE = "INACTIVE"
    STATUS_DISCONTINUED = "DISCONTINUED"
    STATUS_RECALLED = "RECALLED"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_DISCONTINUED, "Discontinued"),
        (STATUS_RECALLED, "Recalled"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="skus")
    sku_code = models.CharField(max_length=100)
    display_name = models.CharField(max_length=255)
    manufactured_product = models.ForeignKey(
        ManufacturedMedicinalProduct, on_delete=models.PROTECT, related_name="skus"
    )
    package_definition = models.ForeignKey(
        PackageDefinition, on_delete=models.PROTECT, related_name="skus"
    )
    default_barcode = models.CharField(max_length=100, blank=True)
    tax_category = models.CharField(max_length=80, default="STANDARD")
    stock_tracking_required = models.BooleanField(default=True)
    batch_tracking_required = models.BooleanField(default=True)
    expiry_tracking_required = models.BooleanField(default=True)
    is_saleable = models.BooleanField(default=True)
    is_purchasable = models.BooleanField(default=True)
    is_dispensable = models.BooleanField(default=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "sku_code"], name="uq_sku_tenant_code")
        ]

    def __str__(self):
        return f"{self.display_name} ({self.sku_code})"


class ProductIdentifier(TimestampedModel):
    ENTITY_TYPES = (
        ("SUBSTANCE", "Active Substance"),
        ("CLINICAL_PRODUCT", "Clinical Medicinal Product"),
        ("MANUFACTURED_PRODUCT", "Manufactured Medicinal Product"),
        ("SKU", "Commercial SKU"),
    )

    entity_type = models.CharField(max_length=50, choices=ENTITY_TYPES)
    entity_id = models.UUIDField()
    system = models.CharField(max_length=150)  # GTIN, EAN, UPC, NationalCode, RegNumber, Legacy
    value = models.CharField(max_length=255)
    issuing_authority = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["system", "value", "entity_type", "entity_id"], name="uq_product_identifier_exact")
        ]
        indexes = [
            models.Index(fields=["system", "value"], name="ix_product_identifier_lookup")
        ]

    def __str__(self):
        return f"{self.system}:{self.value}"


class SubstitutionGroup(TimestampedModel):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    clinical_products = models.ManyToManyField(ClinicalMedicinalProduct, related_name="substitution_groups")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class SubstitutionPolicy(TimestampedModel):
    POLICY_TYPES = (
        ("GENERIC_EQUIVALENT", "Generic Equivalent Only"),
        ("THERAPEUTIC_EQUIVALENT", "Therapeutic Equivalent"),
        ("EXACT_INGREDIENT_MATCH", "Exact Ingredient Match"),
        ("PROHIBITED", "No Substitution Permitted"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="substitution_policies")
    substitution_group = models.ForeignKey(SubstitutionGroup, on_delete=models.CASCADE, related_name="policies")
    policy_type = models.CharField(max_length=50, choices=POLICY_TYPES)
    approval_required = models.BooleanField(default=True)
    reason_required = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "substitution_group"], name="uq_sub_policy_tenant_group")
        ]


class BranchAssortment(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="branch_assortments")
    location = models.ForeignKey("organizations.Location", on_delete=models.CASCADE, related_name="assortments")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.CASCADE, related_name="branch_assortments")
    is_sellable = models.BooleanField(default=True)
    is_purchasable = models.BooleanField(default=True)
    is_dispensable = models.BooleanField(default=True)
    is_stocked = models.BooleanField(default=True)
    formulary_status = models.CharField(max_length=50, default="FORMULARY")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "location", "sku"], name="uq_branch_assortment_tenant_loc_sku")
        ]


# Preserve Backwards-Compatible Legacy Model Bridge for Existing Tests/APIs
class Medicine(TimestampedModel):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_INACTIVE = "INACTIVE"
    STATUS_DISCONTINUED = "DISCONTINUED"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_DISCONTINUED, "Discontinued"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="medicines")
    is_global = models.BooleanField(default=False)
    code = models.CharField(max_length=120)
    generic_name = models.CharField(max_length=255)
    brand_name = models.CharField(max_length=255, blank=True)
    dosage_form = models.CharField(max_length=120, blank=True)
    strength = models.CharField(max_length=120, blank=True)
    gtin = models.CharField(max_length=32, blank=True)
    primary_barcode = models.CharField(max_length=80, blank=True)
    atc_code = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    source = models.CharField(max_length=160)
    source_version = models.CharField(max_length=80)
    licence_identifier = models.CharField(max_length=160, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(tenant__isnull=True, is_global=True)
                    | models.Q(tenant__isnull=False, is_global=False)
                ),
                name="ck_medicine_explicit_scope",
            ),
            models.UniqueConstraint(
                fields=["tenant", "code"],
                condition=models.Q(tenant__isnull=False),
                name="uq_medicine_tenant_code",
            ),
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(tenant__isnull=True, is_global=True),
                name="uq_medicine_global_code",
            ),
        ]

    def clean(self):
        super().clean()
        if self.is_global == bool(self.tenant_id):
            raise ValidationError("Medicine scope must be one tenant or explicitly global.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class MedicineIdentifier(TimestampedModel):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name="identifiers")
    system = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["system", "value"], name="uq_medicine_identifier")]


class TenantCatalogueProduct(TimestampedModel):
    STATUS_SELECTED = "SELECTED"
    STATUS_REMOVED = "REMOVED"
    STATUS_CHOICES = (
        (STATUS_SELECTED, "Selected"),
        (STATUS_REMOVED, "Removed"),
    )

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="catalogue_products",
    )
    master_medicine = models.ForeignKey(
        Medicine,
        on_delete=models.PROTECT,
        related_name="tenant_catalogue_products",
    )
    tenant_code = models.CharField(max_length=120)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_SELECTED,
    )
    selected_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="selected_catalogue_products",
    )
    selected_at = models.DateTimeField()
    removed_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="removed_catalogue_products",
    )
    removed_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "master_medicine"],
                name="uq_tenant_catalogue_master_medicine",
            ),
            models.UniqueConstraint(
                fields=["tenant", "tenant_code"],
                name="uq_tenant_catalogue_code",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.tenant_id:
            raise ValidationError({"tenant": "Tenant ownership is required."})
        if self.master_medicine_id and (
            self.master_medicine.tenant_id is not None
            or not self.master_medicine.is_global
        ):
            raise ValidationError(
                {"master_medicine": "Tenant products must originate from the universal catalogue."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
