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

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.procurement.models import Supplier, SupplierProductAgreement
from apps.workflows.service import emit_event


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
        if agreed_unit_price is None or agreed_unit_price <= 0:
            # A zero-priced agreement makes every order it prices free.
            raise ValidationError("An agreed unit price above zero is required.")
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
