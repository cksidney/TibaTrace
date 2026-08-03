"""Supplier product agreements.

What a named supplier has agreed to charge for a given SKU, and on what terms.
Purchase orders price from these, so an agreement is a commercial commitment
rather than reference data.

This service existed only in a `services.py` that the `services/` package
shadowed, so nothing could reach it. Meanwhile `SupplierProductAgreementViewSet`
was routed and read-only, which left the model visible in the API with no way to
create a row through it at all.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.medicines.provisioning import (
    ASSORTABLE_SKU_STATUSES,
    _is_cold_chain,
    _is_controlled,
)
from apps.procurement.models import Supplier, SupplierProductAgreement
from apps.procurement.services.supplier_qualification_service import (
    COLD_CHAIN_QUALIFICATION,
    CONTROLLED_DRUG_QUALIFICATION,
    SupplierQualificationService,
)
from apps.workflows.service import emit_event

#: Money is stored at two decimal places. Quantizing here rather than letting
#: the database truncate means the price the caller sees is the price stored --
#: silent truncation of 10.999 to 10.99 is a penny per unit nobody agreed to.
PENNY = Decimal("0.01")


def _quantize_price(value) -> Decimal:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("The agreed unit price must be a decimal number.") from exc
    if not amount.is_finite():
        raise ValidationError("The agreed unit price must be finite.")
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


def assert_supplier_may_supply(*, supplier: Supplier, sku) -> None:
    """Refuse a product the supplier is not qualified to supply.

    Controlled medicines and cold-chain lines are the two categories where
    supplying without the licence is a regulatory breach rather than a
    commercial preference, so the check is here -- at the point the commitment
    is made -- rather than at receipt, when the stock is already on site.
    """
    if _is_controlled(sku) and not SupplierQualificationService.holds(
        supplier=supplier, qualification_type=CONTROLLED_DRUG_QUALIFICATION
    ):
        raise ValidationError(
            f"{sku.sku_code} is a controlled medicine and {supplier.supplier_code} "
            f"holds no current {CONTROLLED_DRUG_QUALIFICATION}."
        )
    if _is_cold_chain(sku) and not SupplierQualificationService.holds(
        supplier=supplier, qualification_type=COLD_CHAIN_QUALIFICATION
    ):
        raise ValidationError(
            f"{sku.sku_code} requires cold-chain handling and "
            f"{supplier.supplier_code} holds no current {COLD_CHAIN_QUALIFICATION}."
        )


class SupplierProductAgreementService:
    """Registers and maintains agreed supplier pricing."""

    #: Only a supplier that has cleared governance may be committed to.
    CONTRACTABLE_STATUSES = (Supplier.Status.APPROVED, Supplier.Status.ACTIVE)

    @staticmethod
    @transaction.atomic
    def register_agreement(
        *,
        tenant,
        supplier: Supplier,
        sku,
        agreed_unit_price,
        purchase_unit: str = "pack",
        currency: str = "KES",
        minimum_order_quantity: int = 1,
        lead_time_days: int = 3,
        is_preferred: bool = False,
        actor=None,
    ) -> SupplierProductAgreement:
        """Record what a supplier has agreed to charge for a product.

        Refused for a supplier that has not been approved. An agreement is the
        basis a purchase order prices from, so contracting with a supplier still
        in draft or suspended commits money to a party governance has not
        cleared -- and the suspension exists precisely to stop that.
        """
        if supplier.status not in SupplierProductAgreementService.CONTRACTABLE_STATUSES:
            raise ValidationError(
                f"{supplier.supplier_code} is {supplier.status} and cannot be "
                "contracted with. Approve the supplier first."
            )
        if agreed_unit_price is None:
            raise ValidationError("An agreed unit price above zero is required.")
        agreed_unit_price = _quantize_price(agreed_unit_price)
        if agreed_unit_price <= 0:
            # A zero-priced agreement makes every order it prices free.
            raise ValidationError("An agreed unit price above zero is required.")
        if sku is None:
            raise ValidationError("An agreement requires a SKU.")
        if getattr(sku, "tenant_id", None) != getattr(tenant, "id", None):
            raise ValidationError("The SKU belongs to a different tenant.")
        if getattr(sku, "status", None) not in ASSORTABLE_SKU_STATUSES:
            raise ValidationError(
                f"{sku.sku_code} is {sku.status} and cannot be contracted for."
            )
        if not getattr(sku, "is_purchasable", True):
            raise ValidationError(f"{sku.sku_code} is not purchasable.")

        assert_supplier_may_supply(supplier=supplier, sku=sku)
        if minimum_order_quantity is not None and minimum_order_quantity < 1:
            raise ValidationError("A minimum order quantity of at least one is required.")
        if lead_time_days is not None and lead_time_days < 0:
            raise ValidationError("Lead time cannot be negative.")

        # all_objects with an explicit tenant filter. `objects` is tenant-strict
        # and returns nothing unless tenant context is set on the thread, so
        # get_or_create would never find an existing agreement and would fall
        # through to inserting a duplicate -- which the unique constraint then
        # rejects with an IntegrityError instead of this service's own message.
        agreement, created = SupplierProductAgreement.all_objects.get_or_create(
            tenant=tenant,
            supplier=supplier,
            sku=sku,
            defaults={
                "agreed_unit_price": agreed_unit_price,
                "purchase_unit": purchase_unit,
                "currency": currency,
                "minimum_order_quantity": minimum_order_quantity,
                "lead_time_days": lead_time_days,
                "is_preferred": is_preferred,
                "status": SupplierProductAgreement.Status.ACTIVE,
            },
        )
        if not created:
            # get_or_create silently returns the existing row and ignores the new
            # price, so a caller repricing an agreement would believe it had
            # worked. Repricing is its own act, with its own audit.
            raise ValidationError(
                f"{supplier.supplier_code} already has an agreement for "
                f"{getattr(sku, 'sku_code', sku)}. Reprice it rather than "
                "registering a second one."
            )

        if is_preferred:
            # One preferred supplier per SKU. Two would make "who do we buy this
            # from by default?" ambiguous, and replenishment picks one silently.
            SupplierProductAgreement.all_objects.filter(
                tenant=tenant, sku=sku, is_preferred=True
            ).exclude(pk=agreement.pk).update(is_preferred=False)

        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="SupplierProductAgreement",
            aggregate_id=str(agreement.pk),
            event_type="SupplierProductAgreementCreated",
            payload={
                "supplier_code": supplier.supplier_code,
                "sku_code": getattr(sku, "sku_code", str(sku)),
                "agreed_unit_price": str(agreed_unit_price),
                "currency": currency,
            },
        )
        return agreement

    @staticmethod
    @transaction.atomic
    def reprice_agreement(
        *, agreement: SupplierProductAgreement, agreed_unit_price, actor=None
    ) -> SupplierProductAgreement:
        """Change an agreed price, keeping the previous one in the event trail.

        Separate from registration so that a price change is a deliberate,
        recorded act rather than a side effect of re-submitting a form.
        """
        if agreed_unit_price is None or agreed_unit_price <= 0:
            raise ValidationError("An agreed unit price above zero is required.")

        previous = agreement.agreed_unit_price
        if previous == agreed_unit_price:
            return agreement

        agreement.agreed_unit_price = agreed_unit_price
        agreement.save(update_fields=["agreed_unit_price", "updated_at"])

        emit_event(
            tenant_id=str(agreement.tenant_id),
            aggregate_type="SupplierProductAgreement",
            aggregate_id=str(agreement.pk),
            event_type="SupplierProductAgreementRepriced",
            payload={
                "supplier_code": agreement.supplier.supplier_code,
                "previous_unit_price": str(previous),
                "agreed_unit_price": str(agreed_unit_price),
            },
        )
        return agreement


    @staticmethod
    @transaction.atomic
    def provision_agreement(
        *,
        tenant,
        supplier: Supplier,
        sku,
        agreed_unit_price,
        actor=None,
        **terms,
    ) -> SupplierProductAgreement:
        """Idempotent entry point for onboarding and bulk provisioning.

        `register_agreement` deliberately raises on a second call, so a caller
        repricing by re-registering is told rather than silently ignored. That
        is right for a user action and wrong for a re-runnable provisioning
        job, which must converge rather than fail.

        This returns the existing agreement when the terms already match, and
        reprices through the authoritative path when they do not. It never
        creates a second agreement.
        """
        existing = SupplierProductAgreement.all_objects.filter(
            tenant=tenant, supplier=supplier, sku=sku
        ).first()
        if existing is None:
            return SupplierProductAgreementService.register_agreement(
                tenant=tenant, supplier=supplier, sku=sku,
                agreed_unit_price=agreed_unit_price, actor=actor, **terms,
            )

        wanted = _quantize_price(agreed_unit_price)
        if existing.agreed_unit_price != wanted:
            SupplierProductAgreementService.reprice_agreement(
                agreement=existing, agreed_unit_price=wanted, actor=actor,
            )
            existing.refresh_from_db()

        if terms.get("is_preferred") and not existing.is_preferred:
            existing.is_preferred = True
            existing.save(update_fields=["is_preferred", "updated_at"])
            SupplierProductAgreement.all_objects.filter(
                tenant=tenant, sku=sku, is_preferred=True
            ).exclude(pk=existing.pk).update(is_preferred=False)
        return existing
