"""Catalogue selection and assortment provisioning.

`MedicineCatalogueService` can create catalogue rows, and
`BranchAssortmentService.enable_sku_for_branch` can flip a SKU on for a branch.
Neither validates that the thing being stocked is fit to stock.

That gap matters. `enable_sku_for_branch` sets `is_sellable`, `is_dispensable`,
`is_purchasable` and `is_stocked` to True unconditionally -- so a RECALLED SKU,
or one whose manufactured product has been WITHDRAWN by the regulator, becomes
sellable and dispensable at a branch with no error anywhere. The failure is
silent and the record looks normal afterwards.

This module adds the layer that refuses. A SKU may only enter an assortment if
its whole chain is fit: the commercial SKU is active, the manufactured product
is not suspended or withdrawn, the clinical product is active, the package
definition is active, and the manufacturer is active. Anything else raises and
names which link failed.

Nothing here creates stock. Assortment says "this branch may carry this
product"; it says nothing about quantity, and batches, balances and ledger
entries belong to inventory.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.medicines.models import (
    BranchAssortment,
    ClinicalMedicinalProduct,
    CommercialSKU,
    ManufacturedMedicinalProduct,
    ProductIdentifier,
)
from apps.workflows.service import emit_event

# --- Fitness rules ---------------------------------------------------------

#: A SKU may only be assorted from this state. DRAFT is not yet approved;
#: INACTIVE and DISCONTINUED have been withdrawn commercially; RECALLED is a
#: safety action and is the one that must never be silently re-enabled.
ASSORTABLE_SKU_STATUSES = frozenset({CommercialSKU.STATUS_ACTIVE})

#: REGISTERED means authorised but not yet commercially launched; both it and
#: ACTIVE are fit to stock. SUSPENDED and WITHDRAWN are regulatory actions.
ASSORTABLE_MANUFACTURED_STATUSES = frozenset(
    {
        ManufacturedMedicinalProduct.STATUS_ACTIVE,
        ManufacturedMedicinalProduct.STATUS_REGISTERED,
    }
)

ASSORTABLE_CLINICAL_STATUSES = frozenset({ClinicalMedicinalProduct.STATUS_ACTIVE})

#: Statuses that represent a safety or regulatory withdrawal rather than a
#: commercial decision. Reported separately so the error says which it is.
REGULATORY_BLOCKS = frozenset(
    {
        CommercialSKU.STATUS_RECALLED,
        ManufacturedMedicinalProduct.STATUS_SUSPENDED,
        ManufacturedMedicinalProduct.STATUS_WITHDRAWN,
        ClinicalMedicinalProduct.STATUS_SUSPENDED,
    }
)

COLD_CHAIN_FORMS = frozenset(
    {"INJECTION", "SUSPENSION_INJECTION", "VACCINE", "SOLUTION_INJECTION"}
)


class CatalogueFitnessError(ValidationError):
    """A catalogue record is not fit to be assorted.

    A distinct type because callers legitimately want to skip an unfit product
    and carry on -- a bulk assortment run should not abort because one line was
    recalled -- while still refusing to stock it.
    """

    def __init__(self, sku_code: str, link: str, detail: str):
        self.sku_code = sku_code
        self.link = link
        self.detail = detail
        super().__init__(f"{sku_code}: {link} — {detail}")


@dataclass(frozen=True)
class CatalogueFilters:
    """Selection criteria for choosing SKUs from a tenant catalogue.

    Every field is optional and narrows the result. Left unset, selection
    returns everything fit to assort.
    """

    active_only: bool = True
    #: "OTC", "PRESCRIPTION_ONLY", or None for either.
    prescription_classification: str | None = None
    #: True selects only controlled products, False only uncontrolled.
    controlled: bool | None = None
    cold_chain: bool | None = None
    therapeutic_class_codes: tuple[str, ...] = field(default_factory=tuple)
    dose_form_codes: tuple[str, ...] = field(default_factory=tuple)
    manufacturer_codes: tuple[str, ...] = field(default_factory=tuple)
    #: Require the SKU to carry at least one product identifier (barcode/GTIN).
    require_identifier: bool = False
    #: Require the manufactured product to carry a market authorisation number.
    require_regulatory_provenance: bool = False
    #: Only SKUs already assorted at this branch.
    branch=None


def _is_cold_chain(sku: CommercialSKU) -> bool:
    dose_form = getattr(sku.manufactured_product.clinical_product, "dose_form", None)
    code = (getattr(dose_form, "code", "") or "").upper()
    return code in COLD_CHAIN_FORMS


def _is_controlled(sku: CommercialSKU) -> bool:
    classification = sku.manufactured_product.clinical_product.controlled_classification
    return bool(classification) and classification.upper() != "NONE"


class CatalogueSelectionService:
    """Chooses SKUs from a tenant's catalogue, deterministically."""

    @staticmethod
    def eligible_skus(*, tenant, filters: CatalogueFilters | None = None):
        """Every SKU fit to assort, narrowed by `filters`.

        Ordered by `sku_code`, never by primary key or insertion order: an
        unordered queryset makes a "deterministic" selection depend on how the
        database happened to return rows.
        """
        filters = filters or CatalogueFilters()
        queryset = (
            CommercialSKU.all_objects.filter(tenant=tenant)
            .select_related(
                "manufactured_product",
                "manufactured_product__clinical_product",
                "manufactured_product__clinical_product__dose_form",
                "manufactured_product__manufacturer",
                "package_definition",
            )
            .order_by("sku_code")
        )

        if filters.active_only:
            queryset = queryset.filter(status__in=ASSORTABLE_SKU_STATUSES)
        if filters.prescription_classification:
            queryset = queryset.filter(
                manufactured_product__clinical_product__prescription_classification=(
                    filters.prescription_classification
                )
            )
        if filters.dose_form_codes:
            queryset = queryset.filter(
                manufactured_product__clinical_product__dose_form__code__in=(
                    list(filters.dose_form_codes)
                )
            )
        if filters.manufacturer_codes:
            queryset = queryset.filter(
                manufactured_product__manufacturer__code__in=list(filters.manufacturer_codes)
            )
        if filters.therapeutic_class_codes:
            queryset = queryset.filter(
                manufactured_product__clinical_product__therapeutic_classifications__code__in=(
                    list(filters.therapeutic_class_codes)
                )
            ).distinct()
        if filters.require_regulatory_provenance:
            queryset = queryset.exclude(manufactured_product__market_authorisation_number="")
        if filters.branch is not None:
            assorted = BranchAssortment.all_objects.filter(
                tenant=tenant, location=filters.branch
            ).values_list("sku_id", flat=True)
            queryset = queryset.filter(pk__in=list(assorted))

        results = list(queryset)

        # Applied in Python because both derive from related fields rather than
        # a column, and a partial database filter here would silently disagree
        # with the fitness check below.
        if filters.controlled is not None:
            results = [s for s in results if _is_controlled(s) == filters.controlled]
        if filters.cold_chain is not None:
            results = [s for s in results if _is_cold_chain(s) == filters.cold_chain]
        if filters.require_identifier:
            with_identifiers = set(
                ProductIdentifier.objects.filter(
                    entity_type="SKU", entity_id__in=[s.pk for s in results]
                ).values_list("entity_id", flat=True)
            )
            results = [
                s for s in results if s.pk in with_identifiers or s.default_barcode
            ]
        return results

    @staticmethod
    def select_deterministic(
        *, tenant, count: int, seed: int, filters: CatalogueFilters | None = None
    ) -> list[CommercialSKU]:
        """Choose `count` SKUs reproducibly.

        Ranks candidates by a SHA-256 of (seed, sku_code) rather than shuffling
        with a seeded RNG. The difference matters: a shuffle depends on the size
        and order of the input, so adding one SKU to the catalogue would change
        which of the others were chosen. Hash-ranking changes only the position
        of the new arrival.
        """
        if count < 0:
            raise ValidationError("count cannot be negative.")
        candidates = CatalogueSelectionService.eligible_skus(tenant=tenant, filters=filters)

        def rank(sku: CommercialSKU) -> str:
            key = f"{seed}|{sku.sku_code}".encode("utf-8")
            return hashlib.sha256(key).hexdigest()

        return sorted(candidates, key=rank)[:count]


class CatalogueFitnessService:
    """Answers whether a catalogue record may be stocked."""

    @staticmethod
    def assert_assortable(sku: CommercialSKU) -> None:
        """Raise unless every link in the chain is fit to stock."""
        manufactured = sku.manufactured_product
        clinical = manufactured.clinical_product

        if sku.status not in ASSORTABLE_SKU_STATUSES:
            kind = "recalled" if sku.status in REGULATORY_BLOCKS else "not active"
            raise CatalogueFitnessError(
                sku.sku_code, "commercial SKU", f"status is {sku.status} ({kind})"
            )
        if manufactured.status not in ASSORTABLE_MANUFACTURED_STATUSES:
            raise CatalogueFitnessError(
                sku.sku_code, "manufactured product",
                f"{manufactured.code} status is {manufactured.status}",
            )
        if clinical.status not in ASSORTABLE_CLINICAL_STATUSES:
            raise CatalogueFitnessError(
                sku.sku_code, "clinical product",
                f"{clinical.code} status is {clinical.status}",
            )
        if not sku.package_definition.is_active:
            raise CatalogueFitnessError(
                sku.sku_code, "package definition",
                f"{sku.package_definition.code} is inactive",
            )
        manufacturer = manufactured.manufacturer
        if manufacturer is None:
            raise CatalogueFitnessError(
                sku.sku_code, "manufacturer", "the manufactured product has no manufacturer"
            )
        if not manufacturer.is_active:
            raise CatalogueFitnessError(
                sku.sku_code, "manufacturer", f"{manufacturer.code} is inactive"
            )

    @staticmethod
    def is_assortable(sku: CommercialSKU) -> bool:
        try:
            CatalogueFitnessService.assert_assortable(sku)
        except CatalogueFitnessError:
            return False
        return True


class BranchAssortmentProvisioningService:
    """Decides what a branch is permitted to carry.

    Assortment is a permission, not a quantity. Nothing here writes stock.
    """

    #: Formulary states a branch assortment may hold.
    FORMULARY = "FORMULARY"
    RESTRICTED = "BRANCH_RESTRICTED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    FORMULARY_RESTRICTED = "FORMULARY_RESTRICTED"
    KNOWN_FORMULARY_STATES = frozenset(
        {FORMULARY, RESTRICTED, TEMPORARILY_UNAVAILABLE, FORMULARY_RESTRICTED}
    )

    @staticmethod
    @transaction.atomic
    def provision(
        *,
        tenant,
        branch,
        sku: CommercialSKU,
        formulary_status: str = FORMULARY,
        is_stocked: bool = True,
        actor=None,
    ) -> BranchAssortment:
        """Permit a branch to carry a SKU.

        Idempotent on (tenant, branch, sku), matching the unique constraint.
        Refuses any SKU whose chain is unfit -- the check the existing
        `enable_sku_for_branch` does not perform.
        """
        if branch is None:
            raise ValidationError("A branch assortment requires a branch.")
        if branch.tenant_id != tenant.id:
            raise ValidationError("The branch belongs to a different tenant.")
        if sku.tenant_id != tenant.id:
            raise ValidationError("The SKU belongs to a different tenant.")
        if formulary_status not in BranchAssortmentProvisioningService.KNOWN_FORMULARY_STATES:
            known = ", ".join(sorted(BranchAssortmentProvisioningService.KNOWN_FORMULARY_STATES))
            raise ValidationError(f"Unknown formulary status {formulary_status!r}. Known: {known}")

        CatalogueFitnessService.assert_assortable(sku)

        # An item that is not available cannot also be reported as stocked --
        # that combination is what puts a line on a shelf report that nobody
        # can actually dispense.
        unavailable = formulary_status == BranchAssortmentProvisioningService.TEMPORARILY_UNAVAILABLE
        effective_stocked = False if unavailable else is_stocked

        assortment, created = BranchAssortment.all_objects.update_or_create(
            tenant=tenant,
            location=branch,
            sku=sku,
            defaults={
                "is_sellable": sku.is_saleable and not unavailable,
                "is_purchasable": sku.is_purchasable,
                "is_dispensable": sku.is_dispensable and not unavailable,
                "is_stocked": effective_stocked,
                "formulary_status": formulary_status,
            },
        )
        if created:
            emit_event(
                tenant_id=tenant.pk,
                aggregate_type="MEDICINE_CATALOGUE",
                aggregate_id=str(sku.pk),
                event_type="BranchAssortmentProvisioned",
                payload={
                    "sku_code": sku.sku_code,
                    "branch": str(branch.pk),
                    "formulary_status": formulary_status,
                },
            )
        return assortment

    @staticmethod
    def provision_many(
        *, tenant, branch, skus, formulary_status: str = FORMULARY, actor=None,
        skip_unfit: bool = False,
    ) -> tuple[list[BranchAssortment], list[CatalogueFitnessError]]:
        """Assort many SKUs at one branch.

        With `skip_unfit`, an unfit product is collected and reported rather
        than aborting the run -- but it is never assorted, and the caller gets
        the list back so the skip cannot pass unnoticed.
        """
        provisioned: list[BranchAssortment] = []
        rejected: list[CatalogueFitnessError] = []
        for sku in skus:
            try:
                provisioned.append(
                    BranchAssortmentProvisioningService.provision(
                        tenant=tenant, branch=branch, sku=sku,
                        formulary_status=formulary_status, actor=actor,
                    )
                )
            except CatalogueFitnessError as exc:
                if not skip_unfit:
                    raise
                rejected.append(exc)
        return provisioned, rejected

    @staticmethod
    @transaction.atomic
    def withdraw(*, assortment: BranchAssortment, actor, reason: str) -> BranchAssortment:
        """Stop a branch carrying a SKU, without deleting the record.

        Dispensing history references the assortment, so the row stays and the
        permissions are cleared instead.
        """
        if actor is None:
            raise PermissionDenied("Withdrawing a branch assortment requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Withdrawing a branch assortment requires a reason.")

        assortment.is_sellable = False
        assortment.is_dispensable = False
        assortment.is_purchasable = False
        assortment.is_stocked = False
        assortment.formulary_status = BranchAssortmentProvisioningService.TEMPORARILY_UNAVAILABLE
        assortment.save(
            update_fields=[
                "is_sellable", "is_dispensable", "is_purchasable", "is_stocked",
                "formulary_status", "updated_at",
            ]
        )
        return assortment


class TenantCatalogueProvisioningService:
    """Creates a tenant's commercial listing from the global catalogue.

    A `CommercialSKU` is tenant-scoped by design: it is one pharmacy chain's
    listing of a globally-defined manufactured product in a particular pack.
    The clinical and manufactured products themselves are global reference data
    that this service reads and never writes -- inventing a clinical medicine
    to reach a target would put a product into clinical decision support that
    no regulator ever authorised.

    So provisioning derives SKUs from (global manufactured product x package
    definition) pairs. That is a real listing decision, and it is bounded by
    what the global catalogue actually contains.
    """

    @staticmethod
    def available_global_products():
        """Global manufactured products fit to list, ordered deterministically."""
        return (
            ManufacturedMedicinalProduct.all_objects.filter(
                is_global=True,
                tenant__isnull=True,
                status__in=ASSORTABLE_MANUFACTURED_STATUSES,
                clinical_product__status__in=ASSORTABLE_CLINICAL_STATUSES,
            )
            .select_related("clinical_product", "clinical_product__dose_form", "manufacturer")
            .order_by("code")
        )

    @staticmethod
    @transaction.atomic
    def provision_sku(
        *,
        tenant,
        manufactured_product: ManufacturedMedicinalProduct,
        package_definition,
        sku_code: str,
        display_name: str = "",
        barcode: str = "",
        tax_category: str = "STANDARD",
        actor=None,
    ) -> CommercialSKU:
        """List one global product, in one pack, for a tenant.

        Idempotent on (tenant, sku_code). Refuses a product that is not fit to
        list, so an unfit SKU never reaches the catalogue in the first place --
        rather than being caught later at assortment.
        """
        sku_code = str(sku_code or "").strip()
        if not sku_code:
            raise ValidationError("A SKU requires a code.")
        if manufactured_product is None or package_definition is None:
            raise ValidationError("A SKU requires a manufactured product and a package.")

        # Global reference data must stay global: listing a *tenant-owned*
        # product from another tenant would cross the ownership boundary the
        # is_global constraint exists to hold.
        if manufactured_product.tenant_id not in (None, tenant.id):
            raise ValidationError(
                f"{manufactured_product.code} belongs to another tenant and cannot be listed."
            )
        if manufactured_product.status not in ASSORTABLE_MANUFACTURED_STATUSES:
            raise CatalogueFitnessError(
                sku_code, "manufactured product",
                f"{manufactured_product.code} status is {manufactured_product.status}",
            )
        clinical = manufactured_product.clinical_product
        if clinical.status not in ASSORTABLE_CLINICAL_STATUSES:
            raise CatalogueFitnessError(
                sku_code, "clinical product", f"{clinical.code} status is {clinical.status}"
            )
        if not package_definition.is_active:
            raise CatalogueFitnessError(
                sku_code, "package definition", f"{package_definition.code} is inactive"
            )

        existing = CommercialSKU.all_objects.filter(tenant=tenant, sku_code=sku_code).first()
        if existing is not None:
            return existing

        sku = CommercialSKU.all_objects.create(
            tenant=tenant,
            sku_code=sku_code,
            display_name=display_name or (
                f"{manufactured_product.brand_name} {package_definition.description}"
            )[:255],
            manufactured_product=manufactured_product,
            package_definition=package_definition,
            default_barcode=barcode,
            tax_category=tax_category,
            status=CommercialSKU.STATUS_ACTIVE,
        )
        if barcode:
            # ProductIdentifier is global reference data with no tenant column,
            # so it carries the default manager rather than the tenant-strict
            # pair. entity_id is a UUIDField; pass the pk, not its string form.
            ProductIdentifier.objects.get_or_create(
                entity_type="SKU",
                entity_id=sku.pk,
                system="GTIN",
                value=barcode,
                defaults={"is_primary": True, "issuing_authority": "DEMO_SYNTHETIC"},
            )
        emit_event(
            tenant_id=tenant.pk,
            aggregate_type="MEDICINE_CATALOGUE",
            aggregate_id=str(sku.pk),
            event_type="TenantSKUProvisioned",
            payload={"sku_code": sku_code, "manufactured_product": manufactured_product.code},
        )
        return sku

    @staticmethod
    @transaction.atomic
    def withdraw_sku(*, sku: CommercialSKU, actor, reason: str,
                     status: str = CommercialSKU.STATUS_DISCONTINUED) -> CommercialSKU:
        """Stop listing a SKU. Never deletes: history references it."""
        if actor is None:
            raise PermissionDenied("Withdrawing a SKU requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Withdrawing a SKU requires a reason.")
        if status not in {CommercialSKU.STATUS_INACTIVE, CommercialSKU.STATUS_DISCONTINUED,
                          CommercialSKU.STATUS_RECALLED}:
            raise ValidationError(f"{status!r} is not a withdrawal status.")

        sku.status = status
        sku.is_saleable = False
        sku.is_dispensable = False
        sku.save(update_fields=["status", "is_saleable", "is_dispensable", "updated_at"])

        # A withdrawn SKU must stop being carried anywhere. Leaving branch
        # assortments sellable is precisely how a recalled product stays on a
        # shelf report after being recalled centrally.
        BranchAssortment.all_objects.filter(tenant=sku.tenant, sku=sku).update(
            is_sellable=False, is_dispensable=False, is_purchasable=False, is_stocked=False,
            formulary_status=BranchAssortmentProvisioningService.TEMPORARILY_UNAVAILABLE,
        )
        return sku
