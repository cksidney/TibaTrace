import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Min, Q, Sum
from django.utils import timezone

from apps.customers.models import Customer
from apps.customers.services import CustomerCreditPolicyService
from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
)
from apps.inventory.services import InventoryLedgerService, InventoryReservationService
from apps.sales.models import (
    CustomerPriceAgreement,
    DeliveryLine,
    DeliveryRecord,
    DispatchLine,
    DispatchOrder,
    DispatchPackage,
    Package,
    PackageLine,
    PackingSession,
    PickingTask,
    PickingWave,
    PriceList,
    PriceListEntry,
    PromotionRule,
    Quotation,
    QuotationLine,
    QuotationRevision,
    SalesOrder,
    SalesOrderAllocation,
    SalesOrderHold,
    SalesOrderLine,
    SalesReturnAuthorization,
    SalesReturnLine,
    SubstitutionProposal,
)
from apps.workflows.models import DomainEvent
from apps.workflows.service import emit_event

ZERO = Decimal("0")
MONEY = Decimal("0.01")


def _decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _lock(instance):
    return type(instance).all_objects.select_for_update().get(pk=instance.pk)


def _validate_actor_tenant(actor, tenant_id):
    actor_tenant_id = getattr(actor, "tenant_id", None)
    if actor and actor_tenant_id and str(actor_tenant_id) != str(tenant_id):
        raise ValidationError("Actor belongs to a different tenant.")


def _event_payload(*, actor=None, reason="", **payload):
    payload.update(
        {
            "actor_id": str(actor.pk) if actor else None,
            "reason": reason,
            "version": 1,
        }
    )
    return payload


class CommercialPricingService:
    @staticmethod
    def resolve_price(*, tenant, customer, sku, quantity=1):
        quantity = _decimal(quantity)
        if quantity <= 0:
            raise ValidationError("Pricing quantity must be positive.")
        now = timezone.localdate()

        agreement = (
            CustomerPriceAgreement.all_objects.filter(
                tenant=tenant, customer=customer, sku=sku, is_active=True, effective_from__lte=now
            )
            .filter(Q(effective_to__gte=now) | Q(effective_to__isnull=True))
            .first()
        )

        price_list_ref = ""
        promotion_ref = ""
        base_unit_price = ZERO
        agreed_unit_price = ZERO

        if agreement:
            agreed_unit_price = agreement.agreed_price
            base_unit_price = agreement.agreed_price
        else:
            price_list = None
            profile = getattr(customer, "commercial_profile", None)
            if profile and profile.price_list:
                price_list = profile.price_list
            else:
                price_list = (
                    PriceList.all_objects.filter(
                        tenant=tenant,
                        is_default=True,
                        status=PriceList.Status.ACTIVE,
                        effective_from__lte=now,
                    )
                    .filter(Q(effective_to__gte=now) | Q(effective_to__isnull=True))
                    .first()
                )

            if price_list:
                entry = (
                    PriceListEntry.all_objects.filter(
                        tenant=tenant,
                        price_list=price_list,
                        sku=sku,
                        minimum_quantity__lte=quantity,
                        is_active=True,
                        effective_from__lte=now,
                    )
                    .filter(Q(effective_to__gte=now) | Q(effective_to__isnull=True))
                    .order_by(
                        "-minimum_quantity",
                        "-effective_from",
                    )
                    .first()
                )
                if entry:
                    base_unit_price = entry.unit_price
                    agreed_unit_price = base_unit_price
                    price_list_ref = str(price_list.pk)
            else:
                base_unit_price = getattr(sku, "base_price", Decimal("0.00"))
                agreed_unit_price = base_unit_price

        discount_percentage = agreement.discount_percentage if agreement else ZERO
        promotion = (
            PromotionRule.all_objects.filter(
                tenant=tenant,
                is_active=True,
                minimum_quantity__lte=quantity,
                effective_from__lte=now,
            )
            .filter(
                Q(effective_to__gte=now) | Q(effective_to__isnull=True),
                Q(sku=sku) | Q(sku__isnull=True),
            )
            .order_by("-discount_percentage", "code")
            .first()
        )
        if promotion and promotion.discount_percentage > discount_percentage:
            discount_percentage = promotion.discount_percentage
            promotion_ref = str(promotion.pk)

        discount_amount = (base_unit_price * discount_percentage / Decimal("100")).quantize(MONEY)
        agreed_unit_price = (base_unit_price - discount_amount).quantize(MONEY)

        return {
            "base_unit_price": base_unit_price,
            "agreed_unit_price": agreed_unit_price,
            "discount_amount": discount_amount,
            "discount_percentage": discount_percentage,
            "price_list_ref": price_list_ref,
            "promotion_ref": promotion_ref,
        }


class QuotationService:
    @staticmethod
    @transaction.atomic
    def create_quotation(
        *,
        tenant,
        branch,
        customer,
        delivery_address=None,
        currency="KES",
        salesperson=None,
        created_by,
        customer_reference="",
        notes="",
        terms="",
        valid_until=None,
    ):
        _validate_actor_tenant(created_by, tenant.pk)
        if str(branch.tenant_id) != str(tenant.pk) or str(customer.tenant_id) != str(tenant.pk):
            raise ValidationError("Quotation branch and customer must belong to the tenant.")
        if delivery_address and (
            str(delivery_address.tenant_id) != str(tenant.pk) or delivery_address.customer_id != customer.pk
        ):
            raise ValidationError("Delivery address must belong to the quotation customer and tenant.")
        quotation_number = f"QT-{uuid.uuid4().hex[:8].upper()}"
        quotation = Quotation.objects.create(
            tenant=tenant,
            branch=branch,
            customer=customer,
            quotation_number=quotation_number,
            delivery_address=delivery_address,
            currency=currency,
            salesperson=salesperson,
            created_by=created_by,
            customer_reference=customer_reference,
            notes=notes,
            terms=terms,
            valid_until=valid_until,
            status="DRAFT",
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="Quotation",
            aggregate_id=str(quotation.pk),
            event_type="QuotationCreated",
            payload=_event_payload(
                actor=created_by,
                quotation_number=quotation_number,
                customer_id=str(customer.pk),
            ),
        )
        return quotation

    @staticmethod
    @transaction.atomic
    def add_quotation_line(*, quotation, sku, requested_quantity, unit, pricing_data=None):
        quotation = _lock(quotation)
        if quotation.status != Quotation.Status.DRAFT:
            raise ValidationError("Quotation lines may only be changed while the quotation is DRAFT.")
        requested_quantity = _decimal(requested_quantity)
        if requested_quantity <= 0:
            raise ValidationError("Quotation quantity must be positive.")
        if str(sku.tenant_id) != str(quotation.tenant_id):
            raise ValidationError("Quotation SKU belongs to a different tenant.")
        if pricing_data is None:
            pricing_data = CommercialPricingService.resolve_price(
                tenant=quotation.tenant, customer=quotation.customer, sku=sku, quantity=requested_quantity
            )

        unit_price = _decimal(pricing_data["agreed_unit_price"])
        base_unit_price = _decimal(pricing_data.get("base_unit_price", unit_price))
        discount_amount = _decimal(pricing_data.get("discount_amount", ZERO))
        discount_percentage = _decimal(pricing_data.get("discount_percentage", ZERO))
        tax_rate = _decimal(pricing_data.get("tax_rate", ZERO))
        subtotal = (unit_price * requested_quantity).quantize(MONEY)
        tax_amount = (subtotal * tax_rate).quantize(MONEY)
        total = subtotal + tax_amount

        line = QuotationLine.objects.create(
            tenant=quotation.tenant,
            quotation=quotation,
            sku=sku,
            description_snapshot=str(sku),
            requested_quantity=requested_quantity,
            unit=unit,
            base_unit_price=base_unit_price,
            agreed_unit_price=unit_price,
            discount_amount=discount_amount,
            discount_percentage=discount_percentage,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            line_subtotal=subtotal,
            line_total=total,
            currency=quotation.currency,
            price_list_ref=pricing_data.get("price_list_ref", "") or "",
            promotion_ref=pricing_data.get("promotion_ref", "") or "",
            override_reason=pricing_data.get("override_reason", "") or "",
            price_approved_by=pricing_data.get("price_approved_by"),
        )

        # Update totals
        quotation.subtotal = (quotation.subtotal or Decimal("0.00")) + subtotal
        quotation.tax_total = (quotation.tax_total or ZERO) + tax_amount
        quotation.total = (quotation.total or ZERO) + total
        quotation.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])
        return line

    @staticmethod
    @transaction.atomic
    def submit_quotation(*, quotation):
        quotation = _lock(quotation)
        if quotation.status != "DRAFT":
            raise ValidationError("Only DRAFT quotations can be submitted")
        if not quotation.lines.exists():
            raise ValidationError("A quotation requires at least one line.")
        if quotation.valid_until and quotation.valid_until < timezone.localdate():
            raise ValidationError("An expired quotation cannot be submitted.")
        quotation.status = "SUBMITTED"
        quotation.save()
        emit_event(
            tenant_id=str(quotation.tenant.pk),
            aggregate_type="Quotation",
            aggregate_id=str(quotation.pk),
            event_type="QuotationSubmitted",
            payload={"quotation_number": quotation.quotation_number},
        )
        return quotation

    @staticmethod
    @transaction.atomic
    def approve_quotation(*, quotation, approver):
        quotation = _lock(quotation)
        _validate_actor_tenant(approver, quotation.tenant_id)
        if quotation.status != "SUBMITTED":
            raise ValidationError("Only SUBMITTED quotations can be approved")
        quotation.status = "APPROVED"
        quotation.approved_by = approver
        quotation.save()
        emit_event(
            tenant_id=str(quotation.tenant.pk),
            aggregate_type="Quotation",
            aggregate_id=str(quotation.pk),
            event_type="QuotationApproved",
            payload=_event_payload(actor=approver),
        )
        return quotation

    @staticmethod
    @transaction.atomic
    def send_quotation(*, quotation):
        quotation = _lock(quotation)
        if quotation.status != "APPROVED":
            raise ValidationError("Only APPROVED quotations can be sent")
        quotation.status = "SENT"
        quotation.sent_at = timezone.now()
        quotation.save()
        emit_event(
            tenant_id=str(quotation.tenant.pk),
            aggregate_type="Quotation",
            aggregate_id=str(quotation.pk),
            event_type="QuotationSent",
            payload={"sent_at": quotation.sent_at.isoformat()},
        )
        return quotation

    @staticmethod
    @transaction.atomic
    def accept_quotation(*, quotation):
        quotation = _lock(quotation)
        if quotation.status != "SENT":
            raise ValidationError("Only SENT quotations can be accepted")
        if quotation.valid_until and quotation.valid_until < timezone.localdate():
            quotation.status = Quotation.Status.EXPIRED
            quotation.save(update_fields=["status", "updated_at"])
            raise ValidationError("Quotation has expired.")
        quotation.status = "ACCEPTED"
        quotation.accepted_at = timezone.now()
        quotation.save()
        emit_event(
            tenant_id=str(quotation.tenant.pk),
            aggregate_type="Quotation",
            aggregate_id=str(quotation.pk),
            event_type="QuotationAccepted",
            payload={"accepted_at": quotation.accepted_at.isoformat()},
        )
        return quotation

    @staticmethod
    @transaction.atomic
    def reject_quotation(*, quotation, reason=""):
        quotation = _lock(quotation)
        if quotation.status not in {
            Quotation.Status.DRAFT,
            Quotation.Status.SUBMITTED,
            Quotation.Status.APPROVED,
            Quotation.Status.SENT,
        }:
            raise ValidationError("Quotation cannot be rejected from its current state.")
        quotation.status = "REJECTED"
        quotation.rejected_at = timezone.now()
        quotation.notes = f"{quotation.notes}\nRejection reason: {reason}".strip()
        quotation.save()
        emit_event(
            tenant_id=str(quotation.tenant.pk),
            aggregate_type="Quotation",
            aggregate_id=str(quotation.pk),
            event_type="QuotationRejected",
            payload={"reason": reason},
        )
        return quotation

    @staticmethod
    @transaction.atomic
    def revise_quotation(*, quotation, changed_fields, new_values, reason, actor, previous_values=None):
        quotation = _lock(quotation)
        if quotation.status in {
            Quotation.Status.ACCEPTED,
            Quotation.Status.CONVERTED,
            Quotation.Status.REJECTED,
            Quotation.Status.EXPIRED,
            Quotation.Status.CANCELLED,
        }:
            raise ValidationError("Accepted or terminal quotations cannot be revised.")
        _validate_actor_tenant(actor, quotation.tenant_id)
        changed_field_names = list(changed_fields.keys()) if isinstance(changed_fields, dict) else list(changed_fields)
        disallowed = {"id", "tenant", "quotation_number", "customer", "branch"}
        if disallowed.intersection(changed_field_names):
            raise ValidationError("Immutable quotation identity fields cannot be revised.")
        captured_previous = previous_values or {
            field: getattr(quotation, field) for field in changed_field_names if hasattr(quotation, field)
        }
        revision = QuotationRevision.objects.create(
            tenant=quotation.tenant,
            quotation=quotation,
            revision_number=quotation.revision + 1,
            changed_fields=changed_field_names,
            previous_values=captured_previous,
            new_values=new_values,
            reason=reason,
            actor=actor,
        )
        for field, value in new_values.items():
            if field in changed_field_names and hasattr(quotation, field):
                setattr(quotation, field, value)
        quotation.revision += 1
        if quotation.status in {
            Quotation.Status.SUBMITTED,
            Quotation.Status.APPROVED,
            Quotation.Status.SENT,
        }:
            quotation.status = Quotation.Status.DRAFT
            quotation.approved_by = None
            quotation.sent_at = None
        quotation.save()
        emit_event(
            tenant_id=str(quotation.tenant_id),
            aggregate_type="Quotation",
            aggregate_id=str(quotation.pk),
            event_type="QuotationRevised",
            payload=_event_payload(
                actor=actor,
                reason=reason,
                revision=quotation.revision,
                changed_fields=changed_field_names,
            ),
        )
        return revision

    @staticmethod
    @transaction.atomic
    def convert_quotation(*, quotation, actor):
        quotation = _lock(quotation)
        if quotation.status != "ACCEPTED":
            raise ValidationError("Only ACCEPTED quotations can be converted")
        _validate_actor_tenant(actor, quotation.tenant_id)

        sales_order = SalesOrderService.create_sales_order(
            tenant=quotation.tenant,
            branch=quotation.branch,
            customer=quotation.customer,
            delivery_address=quotation.delivery_address,
            currency=quotation.currency,
            salesperson=quotation.salesperson,
            customer_po_reference=quotation.customer_reference,
            source_quotation=quotation,
            created_by=actor,
        )

        for q_line in quotation.lines.all():
            SalesOrderService.add_order_line(
                sales_order=sales_order,
                sku=q_line.sku,
                requested_quantity=q_line.requested_quantity,
                unit=q_line.unit,
                pricing_data={
                    "base_unit_price": q_line.base_unit_price,
                    "agreed_unit_price": q_line.agreed_unit_price,
                    "discount_amount": q_line.discount_amount,
                    "discount_percentage": q_line.discount_percentage,
                    "tax_rate": q_line.tax_rate,
                    "price_list_ref": q_line.price_list_ref,
                    "promotion_ref": q_line.promotion_ref,
                    "override_reason": q_line.override_reason,
                    "price_approved_by": q_line.price_approved_by,
                },
            )

        quotation.status = "CONVERTED"
        quotation.save()
        emit_event(
            tenant_id=str(quotation.tenant.pk),
            aggregate_type="Quotation",
            aggregate_id=str(quotation.pk),
            event_type="QuotationConverted",
            payload={"sales_order_id": str(sales_order.pk)},
        )
        return sales_order


class SalesOrderService:
    @staticmethod
    @transaction.atomic
    def create_sales_order(
        *,
        tenant,
        branch,
        customer,
        delivery_address=None,
        currency="KES",
        salesperson=None,
        customer_po_reference="",
        requested_delivery_date=None,
        fulfilment_policy="ALLOW_PARTIAL",
        substitution_policy="NO_SUBSTITUTION",
        invoice_policy="ON_DISPATCH",
        source_quotation=None,
        created_by=None,
    ):
        _validate_actor_tenant(created_by or salesperson, tenant.pk)
        if str(branch.tenant_id) != str(tenant.pk) or str(customer.tenant_id) != str(tenant.pk):
            raise ValidationError("Sales order branch and customer must belong to the tenant.")
        if delivery_address and (
            str(delivery_address.tenant_id) != str(tenant.pk) or delivery_address.customer_id != customer.pk
        ):
            raise ValidationError("Delivery address must belong to the sales-order customer and tenant.")
        if source_quotation and str(source_quotation.tenant_id) != str(tenant.pk):
            raise ValidationError("Source quotation belongs to a different tenant.")
        order_number = f"SO-{uuid.uuid4().hex[:8].upper()}"
        sales_order = SalesOrder.objects.create(
            tenant=tenant,
            branch=branch,
            customer=customer,
            order_number=order_number,
            delivery_address=delivery_address,
            currency=currency,
            salesperson=salesperson,
            customer_po_reference=customer_po_reference,
            requested_delivery_date=requested_delivery_date,
            fulfilment_policy=fulfilment_policy,
            substitution_policy=substitution_policy,
            invoice_policy=invoice_policy,
            source_quotation=source_quotation,
            payment_terms_snapshot=customer.payment_terms,
            status="DRAFT",
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="SalesOrder",
            aggregate_id=str(sales_order.pk),
            event_type="SalesOrderCreated",
            payload=_event_payload(
                actor=created_by or salesperson,
                order_number=order_number,
                customer_id=str(customer.pk),
                source_quotation_id=str(source_quotation.pk) if source_quotation else None,
            ),
        )
        return sales_order

    @staticmethod
    @transaction.atomic
    def add_order_line(*, sales_order, sku, requested_quantity, unit, pricing_data=None):
        sales_order = _lock(sales_order)
        if sales_order.status != SalesOrder.Status.DRAFT:
            raise ValidationError("Sales-order lines may only be changed while the order is DRAFT.")
        requested_quantity = _decimal(requested_quantity)
        if requested_quantity <= 0:
            raise ValidationError("Sales-order quantity must be positive.")
        if str(sku.tenant_id) != str(sales_order.tenant_id):
            raise ValidationError("Sales-order SKU belongs to a different tenant.")
        if not sku.is_saleable or sku.status != sku.STATUS_ACTIVE:
            raise ValidationError("SKU is not active and saleable.")
        if pricing_data is None:
            pricing_data = CommercialPricingService.resolve_price(
                tenant=sales_order.tenant, customer=sales_order.customer, sku=sku, quantity=requested_quantity
            )

        unit_price = _decimal(pricing_data["agreed_unit_price"])
        base_unit_price = _decimal(pricing_data.get("base_unit_price", unit_price))
        discount_amount = _decimal(pricing_data.get("discount_amount", ZERO))
        discount_percentage = _decimal(pricing_data.get("discount_percentage", ZERO))
        tax_rate = _decimal(pricing_data.get("tax_rate", ZERO))
        subtotal = (unit_price * requested_quantity).quantize(MONEY)
        tax_amount = (subtotal * tax_rate).quantize(MONEY)
        total = subtotal + tax_amount

        line = SalesOrderLine.objects.create(
            tenant=sales_order.tenant,
            sales_order=sales_order,
            sku=sku,
            description_snapshot=str(sku),
            requested_quantity=requested_quantity,
            approved_quantity=requested_quantity,
            unit=unit,
            base_unit_price=base_unit_price,
            agreed_unit_price=unit_price,
            discount_amount=discount_amount,
            discount_percentage=discount_percentage,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            line_subtotal=subtotal,
            line_total=total,
            currency=sales_order.currency,
            price_list_ref=pricing_data.get("price_list_ref", "") or "",
            promotion_ref=pricing_data.get("promotion_ref", "") or "",
            override_reason=pricing_data.get("override_reason", "") or "",
            price_approved_by=pricing_data.get("price_approved_by"),
        )

        sales_order.subtotal = (sales_order.subtotal or Decimal("0.00")) + subtotal
        sales_order.tax_total = (sales_order.tax_total or ZERO) + tax_amount
        sales_order.total = (sales_order.total or ZERO) + total
        sales_order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])
        return line

    @staticmethod
    @transaction.atomic
    def submit_order(*, sales_order):
        sales_order = _lock(sales_order)
        if sales_order.status != "DRAFT":
            raise ValidationError("Only DRAFT orders can be submitted")
        if not sales_order.lines.exists():
            raise ValidationError("A sales order requires at least one line.")
        if sales_order.requested_delivery_date and sales_order.requested_delivery_date < timezone.localdate():
            raise ValidationError("Requested delivery date cannot be in the past.")
        sales_order.status = "SUBMITTED"
        sales_order.save()
        emit_event(
            tenant_id=str(sales_order.tenant.pk),
            aggregate_type="SalesOrder",
            aggregate_id=str(sales_order.pk),
            event_type="SalesOrderSubmitted",
            payload={},
        )
        return sales_order

    @staticmethod
    @transaction.atomic
    def cancel_order(*, sales_order, reason, actor):
        return SalesCancellationService.cancel_order(
            sales_order=sales_order,
            reason=reason,
            actor=actor,
        )


class SalesApprovalService:
    @staticmethod
    @transaction.atomic
    def approve_order(*, sales_order, approver):
        sales_order = _lock(sales_order)
        _validate_actor_tenant(approver, sales_order.tenant_id)
        if sales_order.status != "SUBMITTED":
            raise ValidationError("Only SUBMITTED orders can be approved")

        if sales_order.customer.status != Customer.Status.ACTIVE:
            raise ValidationError("Customer must be active")

        if sales_order.delivery_address and not getattr(sales_order.delivery_address, "is_active", True):
            raise ValidationError("Delivery address must be active")
        if sales_order.delivery_address and sales_order.delivery_address.customer_id != sales_order.customer_id:
            raise ValidationError("Delivery address does not belong to the order customer.")

        if sales_order.holds.filter(is_active=True).exists():
            raise ValidationError("Cannot approve order with active holds")

        credit_check = CustomerCreditPolicyService.evaluate_order(
            customer=sales_order.customer, order_total=sales_order.total
        )
        if not credit_check["eligible"]:
            raise ValidationError(f"Credit evaluation failed: {credit_check['reason']}")

        profile = getattr(sales_order.customer, "commercial_profile", None)
        if profile:
            if profile.required_purchase_order_reference and not sales_order.customer_po_reference:
                raise ValidationError("Customer purchase-order reference is required.")
            if profile.minimum_order_value and sales_order.total < profile.minimum_order_value:
                raise ValidationError("Order is below the configured minimum order value.")
            if profile.order_limit is not None and sales_order.total > profile.order_limit:
                raise ValidationError("Order exceeds the configured order limit.")
            blocked_sku_ids = set(profile.blocked_skus.values_list("pk", flat=True))
            if blocked_sku_ids and sales_order.lines.filter(sku_id__in=blocked_sku_ids).exists():
                raise ValidationError("Order contains a customer-blocked SKU.")

        for line in sales_order.lines.select_related("sku__manufactured_product__clinical_product"):
            if line.approved_quantity > line.requested_quantity:
                raise ValidationError("Approved quantity cannot exceed requested quantity.")
            clinical_product = line.sku.manufactured_product.clinical_product
            controlled = clinical_product.controlled_classification != "NONE"
            if controlled and not sales_order.customer.controlled_medicine_eligible:
                raise ValidationError("Customer is not eligible for controlled medicines.")
            if controlled and (
                not sales_order.delivery_address or not sales_order.delivery_address.controlled_medicine_capable
            ):
                raise ValidationError("Delivery address cannot receive controlled medicines.")

        sales_order.status = "APPROVED"
        sales_order.approved_by = approver
        sales_order.approved_at = timezone.now()
        sales_order.save()

        emit_event(
            tenant_id=str(sales_order.tenant.pk),
            aggregate_type="SalesOrder",
            aggregate_id=str(sales_order.pk),
            event_type="SalesOrderApproved",
            payload=_event_payload(actor=approver),
        )
        return sales_order

    @staticmethod
    @transaction.atomic
    def place_hold(*, sales_order, hold_type, reason, placed_by):
        sales_order = _lock(sales_order)
        _validate_actor_tenant(placed_by, sales_order.tenant_id)
        if sales_order.status in {
            SalesOrder.Status.CANCELLED,
            SalesOrder.Status.DISPATCHED,
            SalesOrder.Status.PARTIALLY_DELIVERED,
            SalesOrder.Status.DELIVERED,
            SalesOrder.Status.CLOSED,
        }:
            raise ValidationError("Order cannot be held from its current state.")
        if sales_order.holds.filter(is_active=True, hold_type=hold_type).exists():
            return sales_order.holds.get(is_active=True, hold_type=hold_type)
        hold = SalesOrderHold.objects.create(
            tenant=sales_order.tenant,
            sales_order=sales_order,
            hold_type=hold_type,
            reason=reason,
            placed_by=placed_by,
            is_active=True,
        )
        sales_order.status = "ON_HOLD"
        sales_order.save()
        emit_event(
            tenant_id=str(sales_order.tenant.pk),
            aggregate_type="SalesOrder",
            aggregate_id=str(sales_order.pk),
            event_type="SalesOrderHeld",
            payload={"hold_type": hold_type, "reason": reason},
        )
        return hold

    @staticmethod
    @transaction.atomic
    def release_hold(*, hold, released_by, release_reason):
        hold = _lock(hold)
        _validate_actor_tenant(released_by, hold.tenant_id)
        if not hold.is_active:
            return hold
        hold.is_active = False
        hold.released_by = released_by
        hold.release_reason = release_reason
        hold.released_at = timezone.now()
        hold.save()

        sales_order = hold.sales_order
        if not sales_order.holds.filter(is_active=True).exists():
            sales_order.status = SalesOrder.Status.APPROVED if sales_order.approved_at else SalesOrder.Status.SUBMITTED
            sales_order.save()

        emit_event(
            tenant_id=str(sales_order.tenant.pk),
            aggregate_type="SalesOrder",
            aggregate_id=str(sales_order.pk),
            event_type="SalesOrderHoldReleased",
            payload={"hold_id": str(hold.pk)},
        )
        return hold


class SalesReservationService:
    @staticmethod
    @transaction.atomic
    def reserve_order(*, sales_order, actor):
        sales_order = _lock(sales_order)
        _validate_actor_tenant(actor, sales_order.tenant_id)
        if sales_order.status not in {
            SalesOrder.Status.APPROVED,
            SalesOrder.Status.BACKORDERED,
        }:
            raise ValidationError("Only APPROVED orders can be reserved")

        is_partial = False
        for line in SalesOrderLine.all_objects.select_for_update().filter(sales_order=sales_order):
            target_quantity = line.approved_quantity - line.cancelled_quantity
            prefix = f"SO_{sales_order.pk}_L_{line.pk}_LOC_"
            existing_reservations = InventoryReservation.all_objects.filter(
                tenant=sales_order.tenant,
                idempotency_key__startswith=prefix,
                status__in=[
                    InventoryReservation.Status.PENDING,
                    InventoryReservation.Status.ALLOCATED,
                    InventoryReservation.Status.PARTIALLY_FULFILLED,
                ],
            )
            already_reserved = existing_reservations.aggregate(total=Sum("allocated_quantity"))["total"] or ZERO
            remaining = max(target_quantity - already_reserved, ZERO)

            min_expiry = timezone.localdate() + timedelta(days=line.minimum_shelf_life_days or 0)
            eligible_balances = InventoryBalance.all_objects.select_for_update().filter(
                tenant=sales_order.tenant,
                branch=sales_order.branch,
                sku=line.sku,
                available__gt=0,
                location__status=InventoryLocation.Status.ACTIVE,
                inventory_batch__quality_status=InventoryBatch.QualityStatus.RELEASED,
                inventory_batch__recall_status=InventoryBatch.RecallStatus.NONE,
                inventory_batch__expiry_date__gte=min_expiry,
            )
            constraints = line.requested_batch_constraints or {}
            if constraints.get("manufacturer_batch_numbers"):
                eligible_balances = eligible_balances.filter(
                    inventory_batch__manufacturer_batch_number__in=constraints["manufacturer_batch_numbers"]
                )
            if constraints.get("exclude_batch_ids"):
                eligible_balances = eligible_balances.exclude(inventory_batch_id__in=constraints["exclude_batch_ids"])

            locations = (
                eligible_balances.values("location_id")
                .annotate(
                    available_quantity=Sum("available"),
                    earliest_expiry=Min("inventory_batch__expiry_date"),
                    earliest_batch=Min("inventory_batch_id"),
                )
                .order_by(
                    "earliest_expiry",
                    "earliest_batch",
                    "location_id",
                )
            )
            for location_summary in locations:
                if remaining <= 0:
                    break
                reservable = min(
                    _decimal(location_summary["available_quantity"]),
                    remaining,
                )
                if reservable <= 0:
                    continue
                location = InventoryLocation.all_objects.get(
                    pk=location_summary["location_id"],
                    tenant=sales_order.tenant,
                )
                eligible_batch_ids = list(
                    eligible_balances.filter(location=location).values_list(
                        "inventory_batch_id",
                        flat=True,
                    )
                )
                reservation = InventoryReservationService.reserve_stock(
                    tenant=sales_order.tenant,
                    branch=sales_order.branch,
                    source_location=location,
                    sku=line.sku,
                    requested_quantity=reservable,
                    purpose="SALES_ORDER",
                    actor=actor,
                    idempotency_key=f"{prefix}{location.pk}",
                    include_batches=eligible_batch_ids,
                    minimum_expiry_date=min_expiry,
                )
                if reservation.source_document != str(sales_order.pk):
                    reservation.source_document = str(sales_order.pk)
                    reservation.save(update_fields=["source_document", "updated_at"])
                remaining -= reservation.allocated_quantity

            active_reservations = InventoryReservation.all_objects.filter(
                tenant=sales_order.tenant,
                idempotency_key__startswith=prefix,
                status__in=[
                    InventoryReservation.Status.PENDING,
                    InventoryReservation.Status.ALLOCATED,
                    InventoryReservation.Status.PARTIALLY_FULFILLED,
                ],
            )
            line.reserved_quantity = min(
                active_reservations.aggregate(total=Sum("allocated_quantity"))["total"] or ZERO,
                target_quantity,
            )
            line.backordered_quantity = max(
                target_quantity - line.reserved_quantity,
                ZERO,
            )
            line.status = (
                SalesOrderLine.Status.RESERVED
                if line.reserved_quantity == target_quantity
                else SalesOrderLine.Status.BACKORDERED
            )
            line.save(
                update_fields=[
                    "reserved_quantity",
                    "backordered_quantity",
                    "status",
                    "updated_at",
                ]
            )
            is_partial = is_partial or line.backordered_quantity > 0

        sales_order.status = SalesOrder.Status.BACKORDERED if is_partial else SalesOrder.Status.RESERVED
        sales_order.save(update_fields=["status", "updated_at"])

        emit_event(
            tenant_id=str(sales_order.tenant.pk),
            aggregate_type="SalesOrder",
            aggregate_id=str(sales_order.pk),
            event_type="SalesOrderReserved",
            payload=_event_payload(actor=actor, is_partial=is_partial),
        )
        return sales_order


class SalesAllocationService:
    @staticmethod
    @transaction.atomic
    def allocate_order(*, sales_order, actor):
        sales_order = _lock(sales_order)
        _validate_actor_tenant(actor, sales_order.tenant_id)
        if sales_order.status not in {
            SalesOrder.Status.RESERVED,
            SalesOrder.Status.BACKORDERED,
            SalesOrder.Status.PARTIALLY_ALLOCATED,
        }:
            raise ValidationError("Only RESERVED or PARTIALLY_ALLOCATED orders can be allocated")

        is_partial = False
        for line in SalesOrderLine.all_objects.select_for_update().filter(sales_order=sales_order):
            prefix = f"SO_{sales_order.pk}_L_{line.pk}_LOC_"
            reservations = InventoryReservation.all_objects.filter(
                tenant=sales_order.tenant,
                idempotency_key__startswith=prefix,
                status__in=[
                    InventoryReservation.Status.PENDING,
                    InventoryReservation.Status.ALLOCATED,
                    InventoryReservation.Status.PARTIALLY_FULFILLED,
                ],
            )
            for reservation in reservations:
                ledger_entries = InventoryLedgerEntry.all_objects.filter(
                    tenant=sales_order.tenant,
                    source_document_type="RESERVATION",
                    source_document_id=str(reservation.pk),
                    entry_type=InventoryLedgerEntry.EntryType.RESERVATION,
                ).select_related("inventory_batch", "location")
                for entry in ledger_entries:
                    SalesOrderAllocation.all_objects.update_or_create(
                        tenant=sales_order.tenant,
                        sales_order_line=line,
                        inventory_batch=entry.inventory_batch,
                        location=entry.location,
                        defaults={
                            "inventory_reservation": reservation,
                            "quantity": entry.base_quantity_delta,
                            "expiry_date": entry.inventory_batch.expiry_date,
                            "status": SalesOrderAllocation.Status.ALLOCATED,
                        },
                    )

            allocated_total = (
                SalesOrderAllocation.all_objects.filter(
                    tenant=sales_order.tenant,
                    sales_order_line=line,
                    status=SalesOrderAllocation.Status.ALLOCATED,
                ).aggregate(total=Sum("quantity"))["total"]
                or ZERO
            )
            line.allocated_quantity = min(allocated_total, line.reserved_quantity)
            line.status = (
                SalesOrderLine.Status.ALLOCATED
                if line.allocated_quantity == line.approved_quantity
                else SalesOrderLine.Status.BACKORDERED
            )
            line.save(update_fields=["allocated_quantity", "status", "updated_at"])
            is_partial = is_partial or line.allocated_quantity < line.approved_quantity

        sales_order.status = SalesOrder.Status.PARTIALLY_ALLOCATED if is_partial else SalesOrder.Status.ALLOCATED
        sales_order.save(update_fields=["status", "updated_at"])

        emit_event(
            tenant_id=str(sales_order.tenant.pk),
            aggregate_type="SalesOrder",
            aggregate_id=str(sales_order.pk),
            event_type="SalesOrderAllocated",
            payload=_event_payload(actor=actor, is_partial=is_partial),
        )
        return sales_order


class SubstitutionProposalService:
    @staticmethod
    @transaction.atomic
    def propose_substitution(*, sales_order_line, proposed_sku, reason, actor):
        sales_order_line = _lock(sales_order_line)
        _validate_actor_tenant(actor, sales_order_line.tenant_id)
        if sales_order_line.sales_order.substitution_policy in {
            SalesOrder.SubstitutionPolicy.NO_SUBSTITUTION,
            SalesOrder.SubstitutionPolicy.EXACT_SKU_ONLY,
        }:
            raise ValidationError("The sales order does not permit substitution.")
        if str(proposed_sku.tenant_id) != str(sales_order_line.tenant_id):
            raise ValidationError("Proposed SKU belongs to a different tenant.")
        clinical_product = sales_order_line.sku.manufactured_product.clinical_product
        if clinical_product.controlled_classification != "NONE":
            raise ValidationError("Controlled products require a later clinical authorization workflow.")
        proposal = SubstitutionProposal.objects.create(
            tenant=sales_order_line.tenant,
            sales_order_line=sales_order_line,
            requested_sku=sales_order_line.sku,
            proposed_sku=proposed_sku,
            reason=reason,
        )
        emit_event(
            tenant_id=str(sales_order_line.sales_order.tenant.pk),
            aggregate_type="SubstitutionProposal",
            aggregate_id=str(proposal.pk),
            event_type="SubstitutionProposed",
            payload=_event_payload(
                actor=actor,
                requested_sku_id=str(sales_order_line.sku_id),
                proposed_sku_id=str(proposed_sku.pk),
            ),
        )
        return proposal

    @staticmethod
    @transaction.atomic
    def approve_substitution(*, proposal, approver):
        proposal = _lock(proposal)
        _validate_actor_tenant(approver, proposal.tenant_id)
        if proposal.status != SubstitutionProposal.Status.PROPOSED:
            raise ValidationError("Only proposed substitutions can be approved.")
        if not proposal.customer_consent:
            raise ValidationError("Customer consent is required before substitution approval.")
        proposal.status = SubstitutionProposal.Status.APPROVED
        proposal.approver = approver
        proposal.save(update_fields=["status", "approver", "updated_at"])
        emit_event(
            tenant_id=str(proposal.sales_order_line.sales_order.tenant.pk),
            aggregate_type="SubstitutionProposal",
            aggregate_id=str(proposal.pk),
            event_type="SubstitutionApproved",
            payload=_event_payload(actor=approver),
        )
        return proposal


class PickingWaveService:
    @staticmethod
    @transaction.atomic
    def create_wave(*, tenant, branch, scope=None, created_by):
        wave_number = f"WAVE-{uuid.uuid4().hex[:8].upper()}"
        wave = PickingWave.objects.create(
            tenant=tenant,
            branch=branch,
            wave_number=wave_number,
            scope=scope or {},
            created_by=created_by,
            status="DRAFT",
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="PickingWave",
            aggregate_id=str(wave.pk),
            event_type="PickingWaveCreated",
            payload={"wave_number": wave_number},
        )
        return wave

    @staticmethod
    @transaction.atomic
    def release_wave(*, wave):
        wave = _lock(wave)
        if wave.status == PickingWave.Status.RELEASED:
            return wave
        if wave.status != PickingWave.Status.DRAFT:
            raise ValidationError("Only draft picking waves can be released.")
        wave.status = PickingWave.Status.RELEASED
        wave.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=str(wave.tenant.pk),
            aggregate_type="PickingWave",
            aggregate_id=str(wave.pk),
            event_type="PickingWaveReleased",
            payload={},
        )
        return wave


class PickingService:
    @staticmethod
    @transaction.atomic
    def create_picking_task(
        *,
        tenant,
        sales_order,
        sales_order_line,
        allocation,
        source_location,
        sku,
        batch,
        requested_quantity,
        picking_wave=None,
    ):
        requested_quantity = _decimal(requested_quantity)
        if sales_order.status not in {
            SalesOrder.Status.ALLOCATED,
            SalesOrder.Status.PARTIALLY_ALLOCATED,
        }:
            raise ValidationError("Picking requires an allocated sales order.")
        if allocation is None:
            raise ValidationError("Picking tasks require an authoritative sales allocation.")
        if (
            allocation.sales_order_line_id != sales_order_line.pk
            or allocation.inventory_batch_id != getattr(batch, "pk", None)
            or allocation.location_id != source_location.pk
            or sales_order_line.sales_order_id != sales_order.pk
            or sales_order_line.sku_id != sku.pk
        ):
            raise ValidationError("Picking task lineage does not match the sales allocation.")
        if requested_quantity <= 0 or requested_quantity > allocation.quantity:
            raise ValidationError("Picking quantity must be positive and within the allocation.")
        if batch.quality_status != InventoryBatch.QualityStatus.RELEASED:
            raise ValidationError("Only released inventory batches can be picked.")
        if batch.recall_status != InventoryBatch.RecallStatus.NONE:
            raise ValidationError("Recalled or held inventory batches cannot be picked.")
        if batch.expiry_date < timezone.localdate():
            raise ValidationError("Expired inventory batches cannot be picked.")
        if picking_wave and picking_wave.status != PickingWave.Status.RELEASED:
            raise ValidationError("Picking wave must be released.")
        return PickingTask.objects.create(
            tenant=tenant,
            sales_order=sales_order,
            sales_order_line=sales_order_line,
            allocation=allocation,
            source_location=source_location,
            sku=sku,
            batch=batch,
            requested_quantity=requested_quantity,
            picking_wave=picking_wave,
            status="PENDING",
        )

    @staticmethod
    @transaction.atomic
    def assign_task(*, task, picker):
        task = _lock(task)
        _validate_actor_tenant(picker, task.tenant_id)
        if task.status == PickingTask.Status.ASSIGNED and task.assigned_picker_id == picker.pk:
            return task
        if task.status != PickingTask.Status.PENDING:
            raise ValidationError("Only pending picking tasks can be assigned.")
        task.status = PickingTask.Status.ASSIGNED
        task.assigned_picker = picker
        task.save()
        emit_event(
            tenant_id=str(task.tenant.pk),
            aggregate_type="PickingTask",
            aggregate_id=str(task.pk),
            event_type="PickingTaskAssigned",
            payload={"picker_id": str(picker.pk)},
        )
        return task

    @staticmethod
    @transaction.atomic
    def start_task(*, task):
        task = _lock(task)
        if task.status == PickingTask.Status.IN_PROGRESS:
            return task
        if task.status != PickingTask.Status.ASSIGNED:
            raise ValidationError("Only assigned picking tasks can be started.")
        task.status = PickingTask.Status.IN_PROGRESS
        task.started_at = timezone.now()
        task.save()
        return task

    @staticmethod
    @transaction.atomic
    def record_pick(*, task, picked_quantity, short_quantity=0):
        task = _lock(task)
        picked_quantity = _decimal(picked_quantity)
        short_quantity = _decimal(short_quantity)
        if task.status in {PickingTask.Status.PICKED, PickingTask.Status.SHORT_PICK}:
            if task.picked_quantity == picked_quantity and task.short_quantity == short_quantity:
                return task
            raise ValidationError("Completed picking tasks cannot be changed.")
        if task.status != PickingTask.Status.IN_PROGRESS:
            raise ValidationError("Only in-progress picking tasks can record quantities.")
        if picked_quantity < 0 or short_quantity < 0:
            raise ValidationError("Pick quantities cannot be negative.")
        if picked_quantity + short_quantity > task.requested_quantity:
            raise ValidationError("Picked and short quantities exceed the task allocation.")
        if task.allocation_id and picked_quantity > task.allocation.quantity:
            raise ValidationError("Picked quantity exceeds the authoritative allocation.")
        if task.batch.quality_status != InventoryBatch.QualityStatus.RELEASED:
            raise ValidationError("Batch is no longer released for picking.")
        if task.batch.recall_status != InventoryBatch.RecallStatus.NONE:
            raise ValidationError("Batch is recalled or held.")
        if task.batch.expiry_date < timezone.localdate():
            raise ValidationError("Batch expired before picking.")

        task.picked_quantity = picked_quantity
        task.short_quantity = short_quantity
        task.status = PickingTask.Status.PICKED if short_quantity == 0 else PickingTask.Status.SHORT_PICK
        task.completed_at = timezone.now()
        task.save()

        line = SalesOrderLine.all_objects.select_for_update().get(pk=task.sales_order_line_id)
        line.picked_quantity = (
            PickingTask.all_objects.filter(
                tenant=task.tenant,
                sales_order_line=line,
                status__in=[
                    PickingTask.Status.PICKED,
                    PickingTask.Status.SHORT_PICK,
                    PickingTask.Status.VERIFIED,
                ],
            ).aggregate(total=Sum("picked_quantity"))["total"]
            or ZERO
        )
        line.status = (
            SalesOrderLine.Status.PICKED
            if line.picked_quantity == line.allocated_quantity
            else SalesOrderLine.Status.PICKING
        )
        line.save(update_fields=["picked_quantity", "status", "updated_at"])
        order = line.sales_order
        order.status = (
            SalesOrder.Status.PICKED
            if all(order_line.picked_quantity == order_line.allocated_quantity for order_line in order.lines.all())
            else SalesOrder.Status.PARTIALLY_PICKED
        )
        order.save(update_fields=["status", "updated_at"])

        emit_event(
            tenant_id=str(task.tenant.pk),
            aggregate_type="PickingTask",
            aggregate_id=str(task.pk),
            event_type="SalesOrderPicked",
            payload=_event_payload(
                quantity=str(picked_quantity),
                order_id=str(task.sales_order_id),
                order_line_id=str(task.sales_order_line_id),
                sku_id=str(task.sku_id),
                batch_id=str(task.batch_id),
                unit=task.sales_order_line.unit,
            ),
        )
        return task

    @staticmethod
    @transaction.atomic
    def verify_pick(*, task, verifier):
        task = _lock(task)
        _validate_actor_tenant(verifier, task.tenant_id)
        if task.status == PickingTask.Status.VERIFIED:
            return task
        if task.status not in {PickingTask.Status.PICKED, PickingTask.Status.SHORT_PICK}:
            raise ValidationError("Only completed picks can be verified.")
        if task.assigned_picker_id == getattr(verifier, "pk", None):
            raise ValidationError("Picker cannot verify their own picking task.")
        task.status = PickingTask.Status.VERIFIED
        task.save(update_fields=["status", "updated_at"])
        return task


class PackingService:
    @staticmethod
    @transaction.atomic
    def create_session(*, tenant, branch, sales_order, packer):
        _validate_actor_tenant(packer, tenant.pk)
        if sales_order.status not in {
            SalesOrder.Status.PICKED,
            SalesOrder.Status.PARTIALLY_PICKED,
        }:
            raise ValidationError("Packing requires picked stock.")
        session_number = f"PACK-{uuid.uuid4().hex[:8].upper()}"
        return PackingSession.objects.create(
            tenant=tenant, branch=branch, sales_order=sales_order, session_number=session_number, packer=packer
        )

    @staticmethod
    @transaction.atomic
    def create_package(
        *, session, sales_order, delivery_address=None, temperature_zone="AMBIENT", package_type="", packer=None
    ):
        session = _lock(session)
        if session.status not in {
            PackingSession.Status.OPEN,
            PackingSession.Status.PACKING,
        }:
            raise ValidationError("Packing session is not open.")
        if session.sales_order_id != sales_order.pk:
            raise ValidationError("Package order does not match the packing session.")
        if delivery_address and delivery_address.customer_id != sales_order.customer_id:
            raise ValidationError("Package delivery address does not belong to the order customer.")
        session.status = PackingSession.Status.PACKING
        session.save(update_fields=["status", "updated_at"])
        package_number = f"PKG-{uuid.uuid4().hex[:8].upper()}"
        return Package.objects.create(
            tenant=session.tenant,
            packing_session=session,
            sales_order=sales_order,
            package_number=package_number,
            delivery_address=delivery_address,
            temperature_zone=temperature_zone,
            package_type=package_type,
            packer=packer,
            status="OPEN",
        )

    @staticmethod
    @transaction.atomic
    def pack_line(*, package, sales_order_line, picking_task, sku, batch, quantity, unit):
        package = _lock(package)
        quantity = _decimal(quantity)
        if package.status not in {Package.Status.OPEN, Package.Status.PACKING}:
            raise ValidationError("Package is not open for packing.")
        if quantity <= 0:
            raise ValidationError("Packed quantity must be positive.")
        if sales_order_line.sales_order_id != package.sales_order_id:
            raise ValidationError("Package line belongs to a different sales order.")
        if sales_order_line.sku_id != sku.pk:
            raise ValidationError("Packed SKU does not match the sales-order line.")
        if picking_task:
            if picking_task.status != PickingTask.Status.VERIFIED:
                raise ValidationError("Only verified picking tasks may be packed.")
            if (
                picking_task.sales_order_line_id != sales_order_line.pk
                or picking_task.sku_id != sku.pk
                or picking_task.batch_id != getattr(batch, "pk", None)
            ):
                raise ValidationError("Packing lineage does not match the picking task.")
        already_packed = (
            PackageLine.all_objects.filter(
                tenant=package.tenant,
                sales_order_line=sales_order_line,
            ).aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )
        if already_packed + quantity > sales_order_line.picked_quantity:
            raise ValidationError("Cannot pack more than the picked quantity.")
        package.status = Package.Status.PACKING
        package.save(update_fields=["status", "updated_at"])
        line = PackageLine.objects.create(
            tenant=package.sales_order.tenant,
            package=package,
            sales_order_line=sales_order_line,
            picking_task=picking_task,
            sku=sku,
            batch=batch,
            quantity=quantity,
            unit=unit,
        )
        sales_order_line = SalesOrderLine.all_objects.select_for_update().get(pk=sales_order_line.pk)
        sales_order_line.packed_quantity = (
            PackageLine.all_objects.filter(
                tenant=package.tenant,
                sales_order_line=sales_order_line,
            ).aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )
        sales_order_line.status = (
            SalesOrderLine.Status.PACKED
            if sales_order_line.packed_quantity == sales_order_line.picked_quantity
            else SalesOrderLine.Status.PICKED
        )
        sales_order_line.save(update_fields=["packed_quantity", "status", "updated_at"])
        order = sales_order_line.sales_order
        order.status = (
            SalesOrder.Status.PACKED
            if all(order_line.packed_quantity == order_line.picked_quantity for order_line in order.lines.all())
            else SalesOrder.Status.PARTIALLY_PACKED
        )
        order.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=str(package.sales_order.tenant.pk),
            aggregate_type="Package",
            aggregate_id=str(package.pk),
            event_type="SalesOrderPacked",
            payload=_event_payload(
                actor=package.packer,
                quantity=str(quantity),
                order_id=str(package.sales_order_id),
                order_line_id=str(sales_order_line.pk),
                sku_id=str(sku.pk),
                batch_id=str(getattr(batch, "pk", "")) or None,
                unit=unit,
            ),
        )
        return line

    @staticmethod
    @transaction.atomic
    def seal_package(*, package, seal_number, verifier):
        package = _lock(package)
        _validate_actor_tenant(verifier, package.tenant_id)
        if package.status == Package.Status.SEALED:
            if package.seal_number == seal_number:
                return package
            raise ValidationError("A sealed package cannot be resealed with a different seal.")
        if package.status not in {Package.Status.OPEN, Package.Status.PACKING, Package.Status.VERIFIED}:
            raise ValidationError("Package cannot be sealed from its current state.")
        if not package.lines.exists():
            raise ValidationError("An empty package cannot be sealed.")
        if package.packer_id == getattr(verifier, "pk", None):
            raise ValidationError("Packer cannot verify and seal their own package.")
        package.status = Package.Status.SEALED
        package.seal_number = seal_number
        package.verifier = verifier
        package.packed_at = timezone.now()
        package.save(
            update_fields=[
                "status",
                "seal_number",
                "verifier",
                "packed_at",
                "updated_at",
            ]
        )
        emit_event(
            tenant_id=str(package.sales_order.tenant.pk),
            aggregate_type="Package",
            aggregate_id=str(package.pk),
            event_type="PackageSealed",
            payload={"seal_number": seal_number},
        )
        return package


class DispatchService:
    @staticmethod
    @transaction.atomic
    def create_dispatch(
        *,
        tenant,
        branch,
        customer,
        delivery_address,
        sales_order,
        carrier="",
        created_by,
        warehouse=None,
    ):
        _validate_actor_tenant(created_by, tenant.pk)
        if sales_order.status not in {
            SalesOrder.Status.PACKED,
            SalesOrder.Status.PARTIALLY_PACKED,
        }:
            raise ValidationError("Dispatch creation requires packed stock.")
        if (
            sales_order.tenant_id != tenant.pk
            or sales_order.branch_id != branch.pk
            or sales_order.customer_id != customer.pk
        ):
            raise ValidationError("Dispatch references do not match the sales order.")
        if delivery_address.customer_id != customer.pk or not delivery_address.is_active:
            raise ValidationError("Dispatch delivery address is invalid.")
        if warehouse and warehouse.branch_id != branch.pk:
            raise ValidationError("Dispatch warehouse belongs to a different branch.")
        dispatch_number = f"DSP-{uuid.uuid4().hex[:8].upper()}"
        dispatch = DispatchOrder.objects.create(
            tenant=tenant,
            branch=branch,
            sales_order=sales_order,
            warehouse=warehouse,
            customer=customer,
            delivery_address=delivery_address,
            dispatch_number=dispatch_number,
            carrier=carrier,
            created_by=created_by,
            status="DRAFT",
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="DispatchOrder",
            aggregate_id=str(dispatch.pk),
            event_type="DispatchCreated",
            payload=_event_payload(
                actor=created_by,
                dispatch_number=dispatch_number,
                order_id=str(sales_order.pk),
                customer_id=str(customer.pk),
            ),
        )
        return dispatch

    @staticmethod
    @transaction.atomic
    def approve_dispatch(*, dispatch, approver):
        dispatch = _lock(dispatch)
        _validate_actor_tenant(approver, dispatch.tenant_id)
        if dispatch.status == DispatchOrder.Status.APPROVED:
            return dispatch
        if dispatch.status not in {
            DispatchOrder.Status.DRAFT,
            DispatchOrder.Status.READY,
        }:
            raise ValidationError("Dispatch cannot be approved from its current state.")
        if not dispatch.lines.exists():
            raise ValidationError("Dispatch requires at least one line.")
        dispatch.status = DispatchOrder.Status.APPROVED
        dispatch.approved_by = approver
        dispatch.save()
        emit_event(
            tenant_id=str(dispatch.tenant.pk),
            aggregate_type="DispatchOrder",
            aggregate_id=str(dispatch.pk),
            event_type="DispatchApproved",
            payload=_event_payload(actor=approver, order_id=str(dispatch.sales_order_id)),
        )
        return dispatch

    @staticmethod
    @transaction.atomic
    def add_dispatch_line(
        *,
        dispatch,
        sales_order_line,
        package,
        sku,
        batch,
        quantity,
        unit,
        source_location=None,
        idempotency_key=None,
    ):
        dispatch = _lock(dispatch)
        quantity = _decimal(quantity)
        if dispatch.status not in {DispatchOrder.Status.DRAFT, DispatchOrder.Status.READY}:
            raise ValidationError("Dispatch lines cannot be changed after approval.")
        if sales_order_line.sales_order_id != dispatch.sales_order_id:
            raise ValidationError("Dispatch line belongs to a different sales order.")
        if package.sales_order_id != dispatch.sales_order_id or package.status != Package.Status.SEALED:
            raise ValidationError("Dispatch requires a sealed package from the same sales order.")
        package_line = (
            PackageLine.all_objects.filter(
                tenant=dispatch.tenant,
                package=package,
                sales_order_line=sales_order_line,
                sku=sku,
                batch=batch,
            )
            .select_related("picking_task__allocation")
            .first()
        )
        if not package_line:
            raise ValidationError("Dispatch line must preserve package SKU and batch lineage.")
        source_location = (
            source_location
            or getattr(getattr(package_line, "picking_task", None), "source_location", None)
            or dispatch.warehouse
        )
        if not source_location:
            raise ValidationError("Dispatch line requires an exact source location.")
        if source_location.branch_id != dispatch.branch_id:
            raise ValidationError("Dispatch source location belongs to a different branch.")
        already_dispatched = (
            DispatchLine.all_objects.filter(
                tenant=dispatch.tenant,
                sales_order_line=sales_order_line,
            ).aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )
        if quantity <= 0 or already_dispatched + quantity > sales_order_line.packed_quantity:
            raise ValidationError("Dispatch quantity must be positive and within packed quantity.")
        key = idempotency_key or (f"DSP_LINE_{dispatch.pk}_{sales_order_line.pk}_{batch.pk}_{source_location.pk}")
        existing = DispatchLine.all_objects.filter(idempotency_key=key).first()
        if existing:
            return existing
        dispatch.status = DispatchOrder.Status.READY
        dispatch.save(update_fields=["status", "updated_at"])
        return DispatchLine.objects.create(
            tenant=dispatch.tenant,
            dispatch_order=dispatch,
            sales_order_line=sales_order_line,
            package=package,
            source_location=source_location,
            sku=sku,
            batch=batch,
            quantity=quantity,
            unit=unit,
            idempotency_key=key,
        )

    @staticmethod
    @transaction.atomic
    def load_dispatch(*, dispatch, packages, loaded_by):
        dispatch = _lock(dispatch)
        _validate_actor_tenant(loaded_by, dispatch.tenant_id)
        if dispatch.status == DispatchOrder.Status.LOADED:
            return dispatch
        if dispatch.status != DispatchOrder.Status.APPROVED:
            raise ValidationError("Only approved dispatches can be loaded.")
        resolved_packages = []
        for pkg in packages:
            if not isinstance(pkg, Package):
                pkg = Package.all_objects.get(pk=pkg, tenant=dispatch.tenant)
            if pkg.sales_order_id != dispatch.sales_order_id or pkg.status != Package.Status.SEALED:
                raise ValidationError("Only sealed packages for the dispatch order can be loaded.")
            resolved_packages.append(pkg)
        line_package_ids = set(dispatch.lines.values_list("package_id", flat=True))
        if line_package_ids - {pkg.pk for pkg in resolved_packages}:
            raise ValidationError("All dispatch-line packages must be loaded.")
        for pkg in resolved_packages:
            DispatchPackage.all_objects.get_or_create(
                tenant=dispatch.tenant,
                dispatch_order=dispatch,
                package=pkg,
                defaults={"loaded_by": loaded_by, "loaded_at": timezone.now()},
            )
        dispatch.status = DispatchOrder.Status.LOADED
        dispatch.save(update_fields=["status", "updated_at"])
        return dispatch

    @staticmethod
    @transaction.atomic
    def dispatch_order(*, dispatch, dispatched_by):
        dispatch = _lock(dispatch)
        _validate_actor_tenant(dispatched_by, dispatch.tenant_id)
        if dispatch.status == DispatchOrder.Status.DISPATCHED:
            return dispatch
        if dispatch.status != DispatchOrder.Status.LOADED:
            raise ValidationError("Only loaded dispatches can leave custody.")
        if not dispatch.lines.exists():
            raise ValidationError("An empty dispatch cannot leave custody.")

        dispatch.status = DispatchOrder.Status.DISPATCHED
        dispatch.dispatched_by = dispatched_by
        dispatch.dispatch_date = timezone.localdate()
        dispatch.save(update_fields=["status", "dispatched_by", "dispatch_date", "updated_at"])

        for line in dispatch.lines.select_related(
            "sales_order_line",
            "batch",
            "source_location",
        ):
            if not line.source_location_id:
                raise ValidationError("Dispatch line has no source-location lineage.")
            if line.quantity > line.sales_order_line.packed_quantity:
                raise ValidationError("Dispatch quantity exceeds packed quantity.")
            InventoryLedgerService.post_entry(
                tenant=dispatch.tenant,
                branch=dispatch.branch,
                location=line.source_location,
                sku=line.sku,
                entry_type=InventoryLedgerEntry.EntryType.ISSUE,
                quantity_delta=-line.quantity,
                unit=line.unit,
                base_quantity_delta=-line.quantity,
                effective_timestamp=timezone.now(),
                source_document_type="DISPATCH_ORDER",
                source_document_id=str(dispatch.pk),
                idempotency_key=f"ISSUE_DSP_{line.pk}",
                inventory_batch=line.batch,
                actor=dispatched_by,
            )

            allocation = (
                SalesOrderAllocation.all_objects.filter(
                    tenant=dispatch.tenant,
                    sales_order_line=line.sales_order_line,
                    inventory_batch=line.batch,
                    location=line.source_location,
                )
                .select_related("inventory_reservation")
                .first()
            )
            if not allocation or not allocation.inventory_reservation_id:
                raise ValidationError("Dispatch line is not linked to an authoritative reservation.")
            InventoryReservationService.fulfill_reservation(
                reservation=allocation.inventory_reservation,
                quantity=line.quantity,
                inventory_batch=line.batch,
                actor=dispatched_by,
                idempotency_key=f"FULFIL_DSP_{line.pk}",
            )
            so_line = SalesOrderLine.all_objects.select_for_update().get(pk=line.sales_order_line_id)
            so_line.dispatched_quantity = (
                DispatchLine.all_objects.filter(
                    tenant=dispatch.tenant,
                    sales_order_line=so_line,
                    dispatch_order__status=DispatchOrder.Status.DISPATCHED,
                ).aggregate(total=Sum("quantity"))["total"]
                or ZERO
            )
            so_line.status = SalesOrderLine.Status.DISPATCHED
            so_line.save(update_fields=["dispatched_quantity", "status", "updated_at"])
            allocation.status = SalesOrderAllocation.Status.DISPATCHED
            allocation.save(update_fields=["status", "updated_at"])
            emit_event(
                tenant_id=str(dispatch.tenant_id),
                aggregate_type="InventoryLedgerEntry",
                aggregate_id=str(line.pk),
                event_type="InventoryIssuedForSales",
                payload=_event_payload(
                    actor=dispatched_by,
                    order_id=str(dispatch.sales_order_id),
                    order_line_id=str(line.sales_order_line_id),
                    sku_id=str(line.sku_id),
                    batch_id=str(line.batch_id),
                    quantity=str(line.quantity),
                    unit=line.unit,
                    source_document=str(dispatch.pk),
                ),
            )

        order = SalesOrder.all_objects.select_for_update().get(pk=dispatch.sales_order_id)
        order.status = (
            SalesOrder.Status.DISPATCHED
            if all(line.dispatched_quantity == line.packed_quantity for line in order.lines.all())
            else SalesOrder.Status.PARTIALLY_DISPATCHED
        )
        order.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=str(dispatch.tenant.pk),
            aggregate_type="DispatchOrder",
            aggregate_id=str(dispatch.pk),
            event_type="SalesOrderDispatched",
            payload=_event_payload(
                actor=dispatched_by,
                order_id=str(dispatch.sales_order_id),
            ),
        )
        InvoiceEligibilityService.evaluate_eligibility(sales_order=order)
        return dispatch


class DeliveryService:
    @staticmethod
    @transaction.atomic
    def confirm_delivery(
        *,
        dispatch,
        recipient_name,
        recipient_role="",
        recipient_phone="",
        proof_type="",
        signature_ref="",
        photo_ref="",
        coordinates="",
        temperature_evidence="",
        delivery_notes="",
        recorded_by,
        delivery_lines_data,
        idempotency_key=None,
    ):
        dispatch = _lock(dispatch)
        _validate_actor_tenant(recorded_by, dispatch.tenant_id)
        if dispatch.status not in {
            DispatchOrder.Status.DISPATCHED,
            DispatchOrder.Status.IN_TRANSIT,
            DispatchOrder.Status.PARTIALLY_DELIVERED,
        }:
            raise ValidationError("Delivery can only be recorded for a dispatched shipment.")
        if not delivery_lines_data:
            raise ValidationError("Delivery confirmation requires line quantities.")
        canonical = "|".join(
            sorted(
                f"{item.get('dispatch_line_id')}:{item.get('accepted_quantity', 0)}:"
                f"{item.get('rejected_quantity', 0)}:{item.get('damaged_quantity', 0)}:"
                f"{item.get('missing_quantity', 0)}"
                for item in delivery_lines_data
            )
        )
        key = idempotency_key or f"DELIVERY_{uuid.uuid5(uuid.NAMESPACE_URL, str(dispatch.pk) + canonical)}"
        existing = DeliveryRecord.all_objects.filter(
            tenant=dispatch.tenant,
            idempotency_key=key,
        ).first()
        if existing:
            return existing

        validated_lines = []
        any_accepted = False
        for line_data in delivery_lines_data:
            dispatch_line = DispatchLine.all_objects.select_for_update().get(
                pk=line_data["dispatch_line_id"],
                tenant=dispatch.tenant,
                dispatch_order=dispatch,
            )
            quantities = {
                name: _decimal(line_data.get(name, ZERO))
                for name in (
                    "accepted_quantity",
                    "rejected_quantity",
                    "damaged_quantity",
                    "missing_quantity",
                )
            }
            if any(value < 0 for value in quantities.values()):
                raise ValidationError("Delivery quantities cannot be negative.")
            handled = sum(quantities.values(), ZERO)
            already_handled = (
                DeliveryLine.all_objects.filter(
                    tenant=dispatch.tenant,
                    dispatch_line=dispatch_line,
                ).aggregate(
                    total=Sum(
                        F("accepted_quantity") + F("rejected_quantity") + F("damaged_quantity") + F("missing_quantity")
                    )
                )["total"]
                or ZERO
            )
            if handled <= 0 or already_handled + handled > dispatch_line.quantity:
                raise ValidationError("Delivery quantities exceed the remaining dispatched quantity.")
            any_accepted = any_accepted or quantities["accepted_quantity"] > 0
            validated_lines.append((dispatch_line, quantities, handled, line_data))

        if any_accepted and not recipient_name:
            raise ValidationError("Recipient name is required for accepted delivery.")
        if any_accepted and not (proof_type or signature_ref or photo_ref):
            raise ValidationError("Proof of delivery is required for accepted quantities.")

        record = DeliveryRecord.objects.create(
            tenant=dispatch.tenant,
            customer=dispatch.customer,
            delivery_address=dispatch.delivery_address,
            dispatch_order=dispatch,
            recipient_name=recipient_name,
            recipient_role=recipient_role,
            recipient_phone=recipient_phone,
            proof_type=proof_type,
            signature_ref=signature_ref,
            photo_ref=photo_ref,
            coordinates=coordinates,
            temperature_evidence=temperature_evidence,
            delivery_notes=delivery_notes,
            recorded_by=recorded_by,
            idempotency_key=key,
            status="DELIVERED",
            delivered_at=timezone.now(),
        )

        all_accepted = True
        sales_order = dispatch.sales_order
        for dispatch_line, quantities, handled, line_data in validated_lines:
            DeliveryLine.objects.create(
                tenant=dispatch.tenant,
                delivery_record=record,
                dispatch_line=dispatch_line,
                sales_order_line=dispatch_line.sales_order_line,
                sku=dispatch_line.sku,
                batch=dispatch_line.batch,
                dispatched_quantity=handled,
                accepted_quantity=quantities["accepted_quantity"],
                rejected_quantity=quantities["rejected_quantity"],
                damaged_quantity=quantities["damaged_quantity"],
                missing_quantity=quantities["missing_quantity"],
                reason=line_data.get("reason", ""),
            )

            so_line = SalesOrderLine.all_objects.select_for_update().get(pk=dispatch_line.sales_order_line_id)
            so_line.delivered_quantity = (
                DeliveryLine.all_objects.filter(
                    tenant=dispatch.tenant,
                    sales_order_line=so_line,
                ).aggregate(total=Sum("accepted_quantity"))["total"]
                or ZERO
            )
            so_line.status = (
                SalesOrderLine.Status.DELIVERED
                if so_line.delivered_quantity == so_line.dispatched_quantity
                else SalesOrderLine.Status.DISPATCHED
            )
            so_line.save(update_fields=["delivered_quantity", "status", "updated_at"])

            if handled < dispatch_line.quantity or quantities["accepted_quantity"] < handled:
                all_accepted = False

        all_accepted = True
        for dispatch_line in dispatch.lines.all():
            delivered_totals = DeliveryLine.all_objects.filter(
                tenant=dispatch.tenant,
                dispatch_line=dispatch_line,
            ).aggregate(
                accepted=Sum("accepted_quantity"),
                rejected=Sum("rejected_quantity"),
                damaged=Sum("damaged_quantity"),
                missing=Sum("missing_quantity"),
            )
            accepted = delivered_totals["accepted"] or ZERO
            handled = sum(
                (
                    delivered_totals["accepted"] or ZERO,
                    delivered_totals["rejected"] or ZERO,
                    delivered_totals["damaged"] or ZERO,
                    delivered_totals["missing"] or ZERO,
                ),
                ZERO,
            )
            if handled != dispatch_line.quantity or accepted != dispatch_line.quantity:
                all_accepted = False
                break

        record.status = DeliveryRecord.Status.DELIVERED if all_accepted else DeliveryRecord.Status.PARTIALLY_DELIVERED
        record.save(update_fields=["status", "updated_at"])
        dispatch.status = DispatchOrder.Status.DELIVERED if all_accepted else DispatchOrder.Status.PARTIALLY_DELIVERED
        dispatch.save(update_fields=["status", "updated_at"])
        if sales_order:
            sales_order.status = (
                SalesOrder.Status.DELIVERED
                if all(line.delivered_quantity == line.dispatched_quantity for line in sales_order.lines.all())
                else SalesOrder.Status.PARTIALLY_DELIVERED
            )
            sales_order.save(update_fields=["status", "updated_at"])

        emit_event(
            tenant_id=str(dispatch.tenant.pk),
            aggregate_type="DeliveryRecord",
            aggregate_id=str(record.pk),
            event_type="DeliveryConfirmed",
            payload=_event_payload(
                actor=recorded_by,
                order_id=str(getattr(dispatch, "sales_order_id", "") or ""),
                customer_id=str(dispatch.customer_id),
                all_accepted=all_accepted,
                source_document=str(dispatch.pk),
            ),
        )
        if sales_order:
            InvoiceEligibilityService.evaluate_eligibility(sales_order=sales_order)
        return record

    @staticmethod
    @transaction.atomic
    def record_failed_delivery(
        *,
        dispatch,
        failure_reason,
        recorded_by,
        tenant=None,
        customer=None,
        idempotency_key=None,
    ):
        dispatch = _lock(dispatch)
        tenant = tenant or dispatch.tenant
        customer = customer or dispatch.customer
        _validate_actor_tenant(recorded_by, dispatch.tenant_id)
        if dispatch.status not in {
            DispatchOrder.Status.DISPATCHED,
            DispatchOrder.Status.IN_TRANSIT,
            DispatchOrder.Status.PARTIALLY_DELIVERED,
        }:
            raise ValidationError("Only dispatched shipments can fail delivery.")
        key = idempotency_key or f"DELIVERY_FAILED_{dispatch.pk}"
        existing = DeliveryRecord.all_objects.filter(
            tenant=tenant,
            idempotency_key=key,
        ).first()
        if existing:
            return existing
        record = DeliveryRecord.objects.create(
            tenant=tenant,
            customer=customer,
            delivery_address=dispatch.delivery_address,
            dispatch_order=dispatch,
            failure_reason=failure_reason,
            recorded_by=recorded_by,
            idempotency_key=key,
            status=DeliveryRecord.Status.FAILED,
        )
        dispatch.status = DispatchOrder.Status.FAILED
        dispatch.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=str(dispatch.tenant.pk),
            aggregate_type="DeliveryRecord",
            aggregate_id=str(record.pk),
            event_type="DeliveryFailed",
            payload=_event_payload(
                actor=recorded_by,
                reason=failure_reason,
                order_id=str(getattr(dispatch, "sales_order_id", "") or ""),
                customer_id=str(customer.pk),
            ),
        )
        return record


class SalesReturnService:
    @staticmethod
    @transaction.atomic
    def request_return(
        *,
        sales_order,
        customer,
        reason,
        requested_by,
        lines_data,
        idempotency_key=None,
    ):
        sales_order = _lock(sales_order)
        _validate_actor_tenant(requested_by, sales_order.tenant_id)
        if sales_order.status not in {
            SalesOrder.Status.PARTIALLY_DELIVERED,
            SalesOrder.Status.DELIVERED,
            SalesOrder.Status.CLOSED,
        }:
            raise ValidationError("Returns require delivered sales-order quantities.")
        if customer.pk != sales_order.customer_id:
            raise ValidationError("Return customer does not match the sales order.")
        canonical = "|".join(
            sorted(
                f"{item.get('sales_order_line_id')}:{item.get('batch_id') or item.get('inventory_batch_id')}:{item.get('quantity')}"
                for item in lines_data
            )
        )
        key = idempotency_key or f"RETURN_{uuid.uuid5(uuid.NAMESPACE_URL, str(sales_order.pk) + canonical)}"
        existing = SalesReturnAuthorization.all_objects.filter(
            tenant=sales_order.tenant,
            idempotency_key=key,
        ).first()
        if existing:
            return existing
        return_number = f"RTN-{uuid.uuid4().hex[:8].upper()}"
        return_auth = SalesReturnAuthorization.objects.create(
            tenant=sales_order.tenant,
            sales_order=sales_order,
            customer=customer,
            return_number=return_number,
            reason=reason,
            requested_by=requested_by,
            idempotency_key=key,
            status=SalesReturnAuthorization.Status.UNDER_REVIEW,
        )

        for ld in lines_data:
            qty = _decimal(ld["quantity"])
            so_line = SalesOrderLine.all_objects.select_for_update().get(
                pk=ld["sales_order_line_id"],
                tenant=sales_order.tenant,
                sales_order=sales_order,
            )
            already_authorized = (
                SalesReturnLine.all_objects.filter(
                    tenant=sales_order.tenant,
                    sales_order_line=so_line,
                    return_authorization__status__in=[
                        SalesReturnAuthorization.Status.UNDER_REVIEW,
                        SalesReturnAuthorization.Status.APPROVED,
                        SalesReturnAuthorization.Status.AWAITING_RETURN,
                        SalesReturnAuthorization.Status.RECEIVED,
                        SalesReturnAuthorization.Status.INSPECTED,
                        SalesReturnAuthorization.Status.ACCEPTED,
                        SalesReturnAuthorization.Status.CLOSED,
                    ],
                ).aggregate(total=Sum("quantity"))["total"]
                or ZERO
            )
            if qty <= 0 or already_authorized + qty > so_line.delivered_quantity:
                raise ValidationError("Cannot return more than the remaining delivered quantity")
            batch_id = ld.get("inventory_batch_id") or ld.get("batch_id")
            if (
                batch_id
                and not DeliveryLine.all_objects.filter(
                    tenant=sales_order.tenant,
                    sales_order_line=so_line,
                    batch_id=batch_id,
                    accepted_quantity__gt=0,
                ).exists()
            ):
                raise ValidationError("Return batch was not delivered on this sales-order line.")
            SalesReturnLine.objects.create(
                tenant=sales_order.tenant,
                return_authorization=return_auth,
                sales_order_line=so_line,
                sku=so_line.sku,
                batch_id=batch_id,
                quantity=qty,
                condition=ld.get("condition", ""),
                temperature_evidence=ld.get("temperature_evidence", ""),
                recall_context=ld.get("recall_context", ""),
                return_eligibility=ld.get("return_eligibility", "PENDING_REVIEW"),
            )

        emit_event(
            tenant_id=str(sales_order.tenant.pk),
            aggregate_type="SalesReturnAuthorization",
            aggregate_id=str(return_auth.pk),
            event_type="SalesReturnRequested",
            payload=_event_payload(
                actor=requested_by,
                reason=reason,
                return_number=return_number,
                order_id=str(sales_order.pk),
                customer_id=str(customer.pk),
            ),
        )
        return return_auth

    @staticmethod
    @transaction.atomic
    def approve_return(*, return_auth, approver):
        return_auth = _lock(return_auth)
        _validate_actor_tenant(approver, return_auth.tenant_id)
        if return_auth.status == SalesReturnAuthorization.Status.APPROVED:
            return return_auth
        if return_auth.status != SalesReturnAuthorization.Status.UNDER_REVIEW:
            raise ValidationError("Only returns under review can be approved.")
        if return_auth.requested_by_id == getattr(approver, "pk", None):
            raise ValidationError("Return requester cannot approve their own return.")
        return_auth.status = SalesReturnAuthorization.Status.APPROVED
        return_auth.approved_by = approver
        return_auth.save(update_fields=["status", "approved_by", "updated_at"])
        emit_event(
            tenant_id=str(return_auth.tenant.pk),
            aggregate_type="SalesReturnAuthorization",
            aggregate_id=str(return_auth.pk),
            event_type="SalesReturnApproved",
            payload=_event_payload(
                actor=approver,
                order_id=str(return_auth.sales_order_id),
                customer_id=str(return_auth.customer_id),
            ),
        )
        return return_auth

    @staticmethod
    @transaction.atomic
    def receive_return(*, return_auth, received_quantities, received_by=None):
        return_auth = _lock(return_auth)
        _validate_actor_tenant(received_by, return_auth.tenant_id)
        if return_auth.status == SalesReturnAuthorization.Status.RECEIVED:
            return return_auth
        if return_auth.status not in {
            SalesReturnAuthorization.Status.APPROVED,
            SalesReturnAuthorization.Status.AWAITING_RETURN,
        }:
            raise ValidationError("Only approved returns can be received.")

        for line in SalesReturnLine.all_objects.select_for_update().filter(return_authorization=return_auth):
            qty = _decimal(received_quantities.get(str(line.pk), ZERO))
            if qty < 0 or qty > line.quantity:
                raise ValidationError("Received return quantity exceeds authorization.")
            line.received_quantity = qty
            line.save(update_fields=["received_quantity", "updated_at"])

            so_line = SalesOrderLine.all_objects.select_for_update().get(pk=line.sales_order_line_id)
            so_line.returned_quantity = (
                SalesReturnLine.all_objects.filter(
                    tenant=return_auth.tenant,
                    sales_order_line=so_line,
                    return_authorization__status__in=[
                        SalesReturnAuthorization.Status.RECEIVED,
                        SalesReturnAuthorization.Status.INSPECTED,
                        SalesReturnAuthorization.Status.ACCEPTED,
                        SalesReturnAuthorization.Status.CLOSED,
                    ],
                ).aggregate(total=Sum("received_quantity"))["total"]
                or ZERO
            ) + qty
            if so_line.returned_quantity > so_line.delivered_quantity:
                raise ValidationError("Received returns exceed delivered quantity.")
            so_line.save(update_fields=["returned_quantity", "updated_at"])

        return_auth.status = SalesReturnAuthorization.Status.RECEIVED
        return_auth.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=str(return_auth.tenant.pk),
            aggregate_type="SalesReturnAuthorization",
            aggregate_id=str(return_auth.pk),
            event_type="SalesReturnReceived",
            payload=_event_payload(
                actor=received_by,
                order_id=str(return_auth.sales_order_id),
                customer_id=str(return_auth.customer_id),
            ),
        )
        return return_auth


class InvoiceEligibilityService:
    @staticmethod
    def evaluate_eligibility(*, sales_order):
        eligible = False
        policy = sales_order.invoice_policy
        status = sales_order.status

        if policy == "ON_ORDER_APPROVAL" and status in ["APPROVED", "RESERVED", "ALLOCATED", "DISPATCHED", "DELIVERED"]:
            eligible = True
        elif policy == "ON_DISPATCH" and status in ["DISPATCHED", "DELIVERED"]:
            eligible = True
        elif policy == "ON_DELIVERY" and status == "DELIVERED":
            eligible = True
        elif policy == "ON_ACCEPTANCE" and status in ["DELIVERED", "CLOSED"]:
            eligible = True

        if (
            eligible
            and not DomainEvent.all_objects.filter(
                tenant=sales_order.tenant,
                aggregate_type="SalesOrder",
                aggregate_id=sales_order.pk,
                event_type="SalesOrderInvoiceEligible",
            ).exists()
        ):
            eligible_lines = [
                {
                    "sales_order_line_id": str(line.pk),
                    "sku_id": str(line.sku_id),
                    "quantity": str(
                        line.dispatched_quantity
                        if policy == SalesOrder.InvoicePolicy.ON_DISPATCH
                        else line.delivered_quantity or line.approved_quantity
                    ),
                    "unit": line.unit,
                    "line_total": str(line.line_total),
                    "tax_amount": str(line.tax_amount),
                }
                for line in sales_order.lines.all()
            ]
            emit_event(
                tenant_id=str(sales_order.tenant.pk),
                aggregate_type="SalesOrder",
                aggregate_id=str(sales_order.pk),
                event_type="SalesOrderInvoiceEligible",
                payload={
                    "policy": policy,
                    "status": status,
                    "customer_id": str(sales_order.customer_id),
                    "currency": sales_order.currency,
                    "subtotal": str(sales_order.subtotal),
                    "tax_total": str(sales_order.tax_total),
                    "total": str(sales_order.total),
                    "eligible_lines": eligible_lines,
                    "version": 1,
                },
            )
        return eligible


class SalesCancellationService:
    @staticmethod
    @transaction.atomic
    def cancel_order(*, sales_order, reason, actor):
        sales_order = _lock(sales_order)
        _validate_actor_tenant(actor, sales_order.tenant_id)
        if sales_order.status == SalesOrder.Status.CANCELLED:
            return sales_order
        if sales_order.status in {
            SalesOrder.Status.PARTIALLY_DISPATCHED,
            SalesOrder.Status.DISPATCHED,
            SalesOrder.Status.PARTIALLY_DELIVERED,
            SalesOrder.Status.DELIVERED,
            SalesOrder.Status.CLOSED,
        }:
            raise ValidationError("Dispatched orders cannot be cancelled")

        reservations = InventoryReservation.all_objects.filter(
            tenant=sales_order.tenant,
            source_document=str(sales_order.pk),
            status__in=[
                InventoryReservation.Status.PENDING,
                InventoryReservation.Status.ALLOCATED,
                InventoryReservation.Status.PARTIALLY_FULFILLED,
            ],
        )
        for reservation in reservations:
            InventoryReservationService.release_reservation(
                reservation=reservation,
                actor=actor,
            )
        SalesOrderAllocation.all_objects.filter(
            tenant=sales_order.tenant,
            sales_order_line__sales_order=sales_order,
            status__in=[
                SalesOrderAllocation.Status.ALLOCATED,
                SalesOrderAllocation.Status.PICKING,
                SalesOrderAllocation.Status.PICKED,
                SalesOrderAllocation.Status.PACKED,
            ],
        ).update(status=SalesOrderAllocation.Status.CANCELLED)
        PickingTask.all_objects.filter(
            tenant=sales_order.tenant,
            sales_order=sales_order,
        ).exclude(status=PickingTask.Status.CANCELLED).update(status=PickingTask.Status.CANCELLED)
        Package.all_objects.filter(
            tenant=sales_order.tenant,
            sales_order=sales_order,
        ).exclude(status=Package.Status.CANCELLED).update(status=Package.Status.CANCELLED)
        for line in SalesOrderLine.all_objects.select_for_update().filter(sales_order=sales_order):
            line.cancelled_quantity = line.approved_quantity
            line.reserved_quantity = ZERO
            line.allocated_quantity = ZERO
            line.picked_quantity = ZERO
            line.packed_quantity = ZERO
            line.backordered_quantity = ZERO
            line.status = SalesOrderLine.Status.CANCELLED
            line.reason = reason
            line.save(
                update_fields=[
                    "cancelled_quantity",
                    "reserved_quantity",
                    "allocated_quantity",
                    "picked_quantity",
                    "packed_quantity",
                    "backordered_quantity",
                    "status",
                    "reason",
                    "updated_at",
                ]
            )

        sales_order.status = SalesOrder.Status.CANCELLED
        sales_order.cancellation_reason = reason
        sales_order.save(update_fields=["status", "cancellation_reason", "updated_at"])

        emit_event(
            tenant_id=str(sales_order.tenant.pk),
            aggregate_type="SalesOrder",
            aggregate_id=str(sales_order.pk),
            event_type="SalesOrderCancelled",
            payload=_event_payload(actor=actor, reason=reason),
        )
        return sales_order
