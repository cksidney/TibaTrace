from __future__ import annotations

import decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.medicines.models import (
    ActiveSubstance,
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
)
from apps.workflows.service import emit_event


def _emit_medicine_event(event_type: str, tenant, aggregate_id: str, payload: dict):
    tenant_id = getattr(tenant, "pk", tenant) if tenant else None
    if tenant_id:
        emit_event(
            tenant_id=tenant_id,
            aggregate_type="MEDICINE_CATALOGUE",
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload or {},
        )


class MedicineCatalogueService:
    @staticmethod
    @transaction.atomic
    def create_clinical_product(
        *,
        tenant=None,
        is_global=False,
        code: str,
        canonical_name: str,
        dose_form: DoseForm,
        routes=None,
        prescription_classification="PRESCRIPTION_ONLY",
        controlled_classification="NONE",
        antimicrobial_classification="NONE",
        status=ClinicalMedicinalProduct.STATUS_DRAFT,
        actor=None,
    ) -> ClinicalMedicinalProduct:
        product = ClinicalMedicinalProduct.objects.create(
            tenant=tenant,
            is_global=is_global,
            code=code,
            canonical_name=canonical_name,
            dose_form=dose_form,
            prescription_classification=prescription_classification,
            controlled_classification=controlled_classification,
            antimicrobial_classification=antimicrobial_classification,
            status=status,
        )
        if routes:
            product.routes.set(routes)

        _emit_medicine_event(
            event_type="ClinicalMedicinalProductCreated",
            tenant=tenant,
            aggregate_id=str(product.pk),
            payload={"code": code, "canonical_name": canonical_name},
        )
        return product

    @staticmethod
    @transaction.atomic
    def activate_clinical_product(*, product: ClinicalMedicinalProduct, actor=None) -> ClinicalMedicinalProduct:
        if not product.ingredients.exists():
            raise ValidationError("Clinical medicinal product must have at least one active ingredient before activation.")
        product.status = ClinicalMedicinalProduct.STATUS_ACTIVE
        product.save()

        _emit_medicine_event(
            event_type="ClinicalMedicinalProductActivated",
            tenant=product.tenant,
            aggregate_id=str(product.pk),
            payload={"code": product.code},
        )
        return product

    @staticmethod
    @transaction.atomic
    def register_manufactured_product(
        *,
        tenant=None,
        is_global=False,
        code: str,
        brand_name: str,
        clinical_product: ClinicalMedicinalProduct,
        manufacturer: Manufacturer = None,
        market_authorisation_number: str = "",
        status=ManufacturedMedicinalProduct.STATUS_REGISTERED,
        actor=None,
    ) -> ManufacturedMedicinalProduct:
        mfg_product = ManufacturedMedicinalProduct.objects.create(
            tenant=tenant,
            is_global=is_global,
            code=code,
            brand_name=brand_name,
            clinical_product=clinical_product,
            manufacturer=manufacturer,
            market_authorisation_number=market_authorisation_number,
            status=status,
        )
        _emit_medicine_event(
            event_type="ManufacturedMedicinalProductRegistered",
            tenant=tenant,
            aggregate_id=str(mfg_product.pk),
            payload={"brand_name": brand_name, "code": code},
        )
        return mfg_product

    @staticmethod
    @transaction.atomic
    def register_sku(
        *,
        tenant,
        sku_code: str,
        display_name: str,
        manufactured_product: ManufacturedMedicinalProduct,
        package_definition: PackageDefinition,
        default_barcode: str = "",
        tax_category: str = "STANDARD",
        status=CommercialSKU.STATUS_ACTIVE,
        actor=None,
    ) -> CommercialSKU:
        sku = CommercialSKU.objects.create(
            tenant=tenant,
            sku_code=sku_code,
            display_name=display_name,
            manufactured_product=manufactured_product,
            package_definition=package_definition,
            default_barcode=default_barcode,
            tax_category=tax_category,
            status=status,
        )
        if default_barcode:
            ProductIdentifierService.assign_identifier(
                entity_type="SKU",
                entity_id=sku.pk,
                system="BARCODE",
                value=default_barcode,
                is_primary=True,
            )

        _emit_medicine_event(
            event_type="CommercialSKUCreated",
            tenant=tenant,
            aggregate_id=str(sku.pk),
            payload={"sku_code": sku_code, "display_name": display_name},
        )
        return sku


class TenantCatalogueService:
    @staticmethod
    @transaction.atomic
    def select_master_product(*, tenant, master_medicine: Medicine, actor):
        if (
            master_medicine.tenant_id is not None
            or not master_medicine.is_global
        ):
            raise ValidationError(
                "Tenant products must originate from the universal catalogue."
            )

        selection = TenantCatalogueProduct.all_objects.filter(
            tenant=tenant,
            master_medicine=master_medicine,
        ).first()
        created = selection is None
        if selection is None:
            selection = TenantCatalogueProduct(
                tenant=tenant,
                master_medicine=master_medicine,
                tenant_code=master_medicine.code,
                selected_by=actor,
                selected_at=timezone.now(),
            )
        else:
            selection.status = TenantCatalogueProduct.STATUS_SELECTED
            selection.selected_by = actor
            selection.selected_at = timezone.now()
            selection.removed_by = None
            selection.removed_at = None
        selection.save()

        _emit_medicine_event(
            event_type="MasterCatalogueProductSelected",
            tenant=tenant,
            aggregate_id=str(selection.pk),
            payload={
                "master_medicine_id": str(master_medicine.pk),
                "etcd_product_id": master_medicine.code,
            },
        )
        return selection, created

    @staticmethod
    @transaction.atomic
    def remove_master_product(*, selection: TenantCatalogueProduct, actor):
        selection.status = TenantCatalogueProduct.STATUS_REMOVED
        selection.removed_by = actor
        selection.removed_at = timezone.now()
        selection.save()

        _emit_medicine_event(
            event_type="MasterCatalogueProductRemoved",
            tenant=selection.tenant,
            aggregate_id=str(selection.pk),
            payload={
                "master_medicine_id": str(selection.master_medicine_id),
                "etcd_product_id": selection.master_medicine.code,
            },
        )
        return selection


class IngredientCompositionService:
    @staticmethod
    @transaction.atomic
    def add_ingredient(
        *,
        clinical_product: ClinicalMedicinalProduct,
        active_substance: ActiveSubstance,
        numerator_value: decimal.Decimal,
        numerator_unit: str,
        denominator_value: decimal.Decimal = decimal.Decimal("1"),
        denominator_unit: str = "unit",
        role: str = "ACTIVE",
        sequence: int = 1,
    ) -> IngredientComposition:
        if numerator_value <= decimal.Decimal("0"):
            raise ValidationError("Ingredient numerator value must be positive.")
        
        comp = IngredientComposition.objects.create(
            clinical_product=clinical_product,
            active_substance=active_substance,
            numerator_value=numerator_value,
            numerator_unit=numerator_unit,
            denominator_value=denominator_value,
            denominator_unit=denominator_unit,
            role=role,
            sequence=sequence,
        )
        return comp


class PackageHierarchyService:
    @staticmethod
    def validate_no_cycles(package: PackageDefinition, target_parent: PackageDefinition):
        current = target_parent
        visited = {package.pk}
        while current:
            if current.pk in visited:
                raise ValidationError("Package hierarchy cycle detected.")
            visited.add(current.pk)
            current = current.parent_package


class ProductIdentifierService:
    @staticmethod
    @transaction.atomic
    def assign_identifier(
        *,
        entity_type: str,
        entity_id,
        system: str,
        value: str,
        issuing_authority: str = "",
        is_primary: bool = False,
    ) -> ProductIdentifier:
        identifier, _ = ProductIdentifier.objects.update_or_create(
            system=system,
            value=value,
            entity_type=entity_type,
            entity_id=entity_id,
            defaults={"issuing_authority": issuing_authority, "is_primary": is_primary},
        )
        return identifier


class SubstitutionPolicyService:
    @staticmethod
    @transaction.atomic
    def configure_policy(
        *,
        tenant,
        substitution_group: SubstitutionGroup,
        policy_type: str = "GENERIC_EQUIVALENT",
        approval_required: bool = True,
        reason_required: bool = True,
        actor=None,
    ) -> SubstitutionPolicy:
        # all_objects: the lookup half of get_or_create runs through the
        # manager's queryset, which is tenant-strict and matches nothing
        # without thread-local context. It would then fall through to a
        # create and collide with the unique constraint -- an idempotent
        # call that works exactly once. Tenant is already in the kwargs.
        policy, _ = SubstitutionPolicy.all_objects.update_or_create(
            tenant=tenant,
            substitution_group=substitution_group,
            defaults={
                "policy_type": policy_type,
                "approval_required": approval_required,
                "reason_required": reason_required,
                "is_active": True,
            },
        )
        _emit_medicine_event(
            event_type="SubstitutionPolicyApproved",
            tenant=tenant,
            aggregate_id=str(substitution_group.pk),
            payload={"policy_type": policy_type},
        )
        return policy


class BranchAssortmentService:
    @staticmethod
    @transaction.atomic
    def enable_sku_for_branch(*, tenant, location, sku: CommercialSKU, actor=None) -> BranchAssortment:
        # all_objects: the lookup half of get_or_create runs through the
        # manager's queryset, which is tenant-strict and matches nothing
        # without thread-local context. It would then fall through to a
        # create and collide with the unique constraint -- an idempotent
        # call that works exactly once. Tenant is already in the kwargs.
        assortment, _ = BranchAssortment.all_objects.update_or_create(
            tenant=tenant,
            location=location,
            sku=sku,
            defaults={"is_sellable": True, "is_purchasable": True, "is_dispensable": True, "is_stocked": True},
        )
        _emit_medicine_event(
            event_type="BranchAssortmentEnabled",
            tenant=tenant,
            aggregate_id=str(sku.pk),
            payload={"location_id": str(location.pk)},
        )
        return assortment


class ManufacturerRegistrationService:
    """Registers the manufacturers that products are attributed to.

    `Manufacturer` carries a scope constraint: a row is either global
    (tenant NULL, is_global True) or tenant-owned (tenant set, is_global
    False), never both and never neither. Nothing enforced that pairing before
    a row reached the database, so a caller could set `is_global` on a
    tenant-owned manufacturer and get a constraint violation naming a check
    rather than the mistake.
    """

    @staticmethod
    @transaction.atomic
    def register_tenant_manufacturer(
        *,
        tenant,
        code: str,
        legal_name: str,
        country: str = "",
        trading_name: str = "",
        regulator_identifier: str = "",
        actor=None,
    ) -> Manufacturer:
        """Register a manufacturer owned by one tenant.

        Idempotent on (tenant, code), matching the partial unique constraint.
        """
        code = str(code or "").strip()
        legal_name = str(legal_name or "").strip()
        if not code:
            raise ValidationError("A manufacturer requires a code.")
        if not legal_name:
            raise ValidationError("A manufacturer requires a legal name.")
        if tenant is None:
            raise ValidationError(
                "A tenant manufacturer requires a tenant. Use "
                "register_global_manufacturer for catalogue-wide entries."
            )

        existing = Manufacturer.all_objects.filter(tenant=tenant, code=code).first()
        if existing is not None:
            return existing

        return Manufacturer.all_objects.create(
            tenant=tenant,
            is_global=False,
            code=code,
            legal_name=legal_name,
            trading_name=trading_name,
            country=country,
            regulator_identifier=regulator_identifier,
            is_active=True,
        )

    @staticmethod
    @transaction.atomic
    def register_global_manufacturer(
        *,
        code: str,
        legal_name: str,
        country: str = "",
        trading_name: str = "",
        regulator_identifier: str = "",
        actor=None,
    ) -> Manufacturer:
        """Register a manufacturer visible to every tenant.

        Global rows are shared reference data, so this is deliberately separate
        from the tenant path: creating one is a catalogue-wide act.
        """
        code = str(code or "").strip()
        legal_name = str(legal_name or "").strip()
        if not code:
            raise ValidationError("A manufacturer requires a code.")
        if not legal_name:
            raise ValidationError("A manufacturer requires a legal name.")

        existing = Manufacturer.all_objects.filter(
            tenant__isnull=True, is_global=True, code=code
        ).first()
        if existing is not None:
            return existing

        return Manufacturer.all_objects.create(
            tenant=None,
            is_global=True,
            code=code,
            legal_name=legal_name,
            trading_name=trading_name,
            country=country,
            regulator_identifier=regulator_identifier,
            is_active=True,
        )

    @staticmethod
    @transaction.atomic
    def deactivate(*, manufacturer: Manufacturer, actor, reason: str) -> Manufacturer:
        """Stop new products being attributed to a manufacturer.

        Existing products keep their attribution: a manufacturer ceasing to
        trade does not change who made the stock already on the shelf.
        """
        if actor is None:
            raise PermissionDenied("Deactivating a manufacturer requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Deactivating a manufacturer requires a reason.")

        manufacturer.is_active = False
        manufacturer.save(update_fields=["is_active", "updated_at"])
        return manufacturer
