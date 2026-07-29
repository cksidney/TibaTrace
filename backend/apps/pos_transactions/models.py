from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel

MONEY = {"max_digits": 15, "decimal_places": 2}
QUANTITY = {"max_digits": 15, "decimal_places": 4}


def transaction_number() -> str:
    return f"PTX-{uuid.uuid4().hex[:20].upper()}"


class PosTransaction(TenantConsistencyMixin, TimestampedModel):
    class State(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        HELD = "HELD", "Held"
        READY_FOR_PAYMENT = "READY_FOR_PAYMENT", "Ready for payment"
        PAYMENT_IN_PROGRESS = "PAYMENT_IN_PROGRESS", "Payment in progress"
        PAID = "PAID", "Paid"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"
        VOIDED = "VOIDED", "Voided"

    class Channel(models.TextChoices):
        RETAIL = "RETAIL", "Retail"

    tenant_relation_fields = (
        "branch", "store", "register", "register_session", "operator_shift",
        "business_day", "operator", "customer", "patient",
    )
    IMMUTABLE_CONTEXT_STATES = frozenset(
        {State.PAYMENT_IN_PROGRESS, State.PAID, State.COMPLETED, State.VOIDED}
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="pos_transactions")
    transaction_number = models.CharField(max_length=32, default=transaction_number)
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="pos_transactions")
    store = models.ForeignKey("inventory.InventoryLocation", on_delete=models.PROTECT, related_name="pos_transactions")
    register = models.ForeignKey("pos_shift.PosRegister", on_delete=models.PROTECT, related_name="transactions")
    register_session = models.ForeignKey(
        "pos_shift.RegisterSession", on_delete=models.PROTECT, related_name="transactions"
    )
    operator_shift = models.ForeignKey(
        "pos_shift.OperatorShift", on_delete=models.PROTECT, related_name="transactions"
    )
    business_day = models.ForeignKey(
        "pos_shift.BusinessDay", on_delete=models.PROTECT, related_name="transactions"
    )
    operator = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="pos_transactions")
    device_id = models.CharField(max_length=128)
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="pos_transactions"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True, related_name="pos_transactions"
    )
    state = models.CharField(max_length=24, choices=State.choices, default=State.DRAFT, db_index=True)
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.RETAIL)
    currency = models.CharField(max_length=3, default="KES")
    subtotal = models.DecimalField(default=Decimal("0.00"), **MONEY)
    discount_total = models.DecimalField(default=Decimal("0.00"), **MONEY)
    tax_total = models.DecimalField(default=Decimal("0.00"), **MONEY)
    total = models.DecimalField(default=Decimal("0.00"), **MONEY)
    hold_reason = models.TextField(blank=True, default="")
    held_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "transaction_number"], name="uq_pos_transaction_tenant_number"
            ),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0), name="chk_pos_transaction_subtotal_nonneg"),
            models.CheckConstraint(condition=models.Q(discount_total__gte=0), name="chk_pos_transaction_discount_nonneg"),
            models.CheckConstraint(condition=models.Q(tax_total__gte=0), name="chk_pos_transaction_tax_nonneg"),
            models.CheckConstraint(condition=models.Q(total__gte=0), name="chk_pos_transaction_total_nonneg"),
        ]
        indexes = [
            models.Index(fields=["tenant", "state"], name="ix_pos_transaction_state"),
            models.Index(fields=["tenant", "register_session"], name="ix_pos_transaction_session"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            existing = (
                PosTransaction.all_objects.filter(pk=self.pk, tenant_id=self.tenant_id)
                .values(
                    "state", "branch_id", "store_id", "register_id", "register_session_id",
                    "operator_shift_id", "business_day_id", "operator_id", "device_id",
                )
                .first()
            )
            if existing and existing["state"] in self.IMMUTABLE_CONTEXT_STATES:
                context = (
                    "branch_id", "store_id", "register_id", "register_session_id",
                    "operator_shift_id", "business_day_id", "operator_id", "device_id",
                )
                if any(getattr(self, field) != existing[field] for field in context):
                    raise ValidationError("A paid POS transaction cannot move to another register context.")
        return super().save(*args, **kwargs)


class PosTransactionLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("transaction", "sku")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="pos_transaction_lines")
    transaction = models.ForeignKey(PosTransaction, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="pos_transaction_lines")
    description_snapshot = models.CharField(max_length=500)
    unit = models.CharField(max_length=50)
    quantity = models.DecimalField(**QUANTITY)
    unit_price = models.DecimalField(**MONEY)
    discount_amount = models.DecimalField(default=Decimal("0.00"), **MONEY)
    tax_amount = models.DecimalField(default=Decimal("0.00"), **MONEY)
    line_total = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default="KES")
    price_snapshot = models.JSONField(default=dict)
    scan_source = models.CharField(max_length=20, default="SEARCH")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["transaction", "sku"], name="uq_pos_transaction_line_sku"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="chk_pos_transaction_line_qty_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="chk_pos_transaction_line_price_nonneg"),
            models.CheckConstraint(condition=models.Q(line_total__gte=0), name="chk_pos_transaction_line_total_nonneg"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding and self.transaction.state not in {
            PosTransaction.State.DRAFT,
            PosTransaction.State.HELD,
        }:
            raise ValidationError("Only draft or held POS transaction lines may be changed.")
        return super().save(*args, **kwargs)


class PosTransactionInventoryContext(TenantConsistencyMixin, TimestampedModel):
    class StockState(models.TextChoices):
        IN_STOCK = "IN_STOCK", "In stock"
        OUT_OF_STOCK = "OUT_OF_STOCK", "Out of stock"
        INSUFFICIENT = "INSUFFICIENT", "Insufficient stock"
        NOT_TRACKED = "NOT_TRACKED", "Stock not tracked"

    tenant_relation_fields = ("transaction_line", "store")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="pos_inventory_contexts")
    transaction_line = models.OneToOneField(
        PosTransactionLine, on_delete=models.CASCADE, related_name="inventory_context"
    )
    store = models.ForeignKey("inventory.InventoryLocation", on_delete=models.PROTECT, related_name="pos_inventory_contexts")
    available_quantity = models.DecimalField(default=Decimal("0.0000"), **QUANTITY)
    stock_state = models.CharField(max_length=20, choices=StockState.choices)
    policy = models.JSONField(default=dict)

    objects = StrictTenantManager()
    all_objects = models.Manager()
