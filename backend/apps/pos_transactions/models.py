from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import StrictTenantManager, StrictTenantQuerySet, TenantConsistencyMixin, TimestampedModel

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
                    "customer_id", "patient_id", "channel", "currency",
                    "subtotal", "discount_total", "tax_total", "total",
                )
                .first()
            )
            if existing and existing["state"] in self.IMMUTABLE_CONTEXT_STATES:
                context = (
                    "branch_id", "store_id", "register_id", "register_session_id",
                    "operator_shift_id", "business_day_id", "operator_id", "device_id",
                    "customer_id", "patient_id", "channel", "currency",
                )
                if any(getattr(self, field) != existing[field] for field in context):
                    raise ValidationError("A paid POS transaction cannot move to another register context.")
                if self.state != existing["state"] and not (existing["state"] == self.State.PAYMENT_IN_PROGRESS and self.state in {self.State.COMPLETED, self.State.VOIDED}):
                    raise ValidationError("A completed POS transaction cannot be reopened or reclassified.")
                financial = ("subtotal", "discount_total", "tax_total", "total")
                if any(getattr(self, field) != existing[field] for field in financial):
                    raise ValidationError("A completed POS transaction total is immutable.")
        return super().save(*args, **kwargs)


class PosTransactionLineQuerySet(StrictTenantQuerySet):
    EDITABLE_STATES = ("DRAFT", "HELD")

    def _ensure_editable(self):
        if self.exclude(transaction__state__in=self.EDITABLE_STATES).exists():
            raise ValidationError("Only draft or held POS transaction lines may be changed.")

    def update(self, **kwargs):
        self._ensure_editable()
        return super().update(**kwargs)

    def delete(self):
        self._ensure_editable()
        return super().delete()


class PosTransactionLineManager(StrictTenantManager):
    def _base_queryset(self):
        return PosTransactionLineQuerySet(self.model, using=self._db)


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
    unit_evidence = models.JSONField(default=list, blank=True)

    objects = PosTransactionLineManager()
    all_objects = models.Manager.from_queryset(PosTransactionLineQuerySet)()

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

    def delete(self, *args, **kwargs):
        if self.transaction.state not in {PosTransaction.State.DRAFT, PosTransaction.State.HELD}:
            raise ValidationError("Only draft or held POS transaction lines may be changed.")
        return super().delete(*args, **kwargs)


def retail_receipt_number() -> str:
    return f"RCP-{uuid.uuid4().hex[:18].upper()}"


class RetailCashReceiptQuerySet(StrictTenantQuerySet):
    def update(self, **kwargs):
        raise ValidationError("Retail cash receipts are immutable.")

    def delete(self):
        raise ValidationError("Retail cash receipts are immutable and cannot be deleted.")


class RetailCashReceiptManager(StrictTenantManager):
    def _base_queryset(self):
        return RetailCashReceiptQuerySet(self.model, using=self._db)


class RetailCashReceipt(TenantConsistencyMixin, TimestampedModel):
    """Immutable evidence of cash received for a completed retail transaction."""

    tenant_relation_fields = ("transaction", "created_by")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="retail_cash_receipts")
    transaction = models.OneToOneField(
        PosTransaction, on_delete=models.PROTECT, related_name="cash_receipt"
    )
    receipt_number = models.CharField(max_length=32, default=retail_receipt_number)
    tender_type = models.CharField(max_length=12, choices=(("CASH", "Cash"), ("CARD", "Card"), ("MPESA", "M-PESA"), ("SPLIT", "Split tender")), default="CASH")
    amount = models.DecimalField(**MONEY)
    cash_received = models.DecimalField(**MONEY)
    change_due = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default="KES")
    lines_snapshot = models.JSONField(default=list)
    totals_snapshot = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=255)
    settled_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    objects = RetailCashReceiptManager()
    all_objects = models.Manager.from_queryset(RetailCashReceiptQuerySet)()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(tender_type__in=["CASH", "CARD", "MPESA", "SPLIT"]), name="chk_retail_receipt_tender_type"),
            models.UniqueConstraint(
                fields=["tenant", "receipt_number"], name="uq_retail_cash_receipt_number"
            ),
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="uq_retail_cash_receipt_idempotency"
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="chk_retail_cash_receipt_amount_positive"),
            models.CheckConstraint(
                condition=~models.Q(tender_type="CASH") | models.Q(cash_received__gte=models.F("amount")),
                name="chk_retail_cash_receipt_tender_covers_total",
            ),
            models.CheckConstraint(condition=models.Q(change_due__gte=0), name="chk_retail_cash_receipt_change_nonneg"),
            models.CheckConstraint(
                condition=~models.Q(tender_type="CASH") | models.Q(change_due=models.F("cash_received") - models.F("amount")),
                name="chk_retail_cash_receipt_change_matches",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and RetailCashReceipt.all_objects.filter(tenant_id=self.tenant_id, pk=self.pk).exists():
            raise ValidationError("Retail cash receipts are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Retail cash receipts are immutable and cannot be deleted.")


class RetailRefundRequest(TenantConsistencyMixin, TimestampedModel):
    """A refund proposal; approval does not yet hand money or stock back."""

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        COMPLETED = "COMPLETED", "Completed"

    tenant_relation_fields = ("transaction", "original_receipt", "return_location", "requested_by", "approved_by")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    transaction = models.ForeignKey(PosTransaction, on_delete=models.PROTECT, related_name="refund_requests")
    original_receipt = models.ForeignKey(RetailCashReceipt, on_delete=models.PROTECT, related_name="refund_requests")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    reason = models.TextField()
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3)
    return_location = models.ForeignKey("inventory.InventoryLocation", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    requested_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=255)
    request_fingerprint = models.CharField(max_length=64)
    payment_plan = models.JSONField(default=list)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uq_retail_refund_request_key"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="chk_retail_refund_request_positive"),
            models.CheckConstraint(condition=~models.Q(approved_by=models.F("requested_by")), name="chk_retail_refund_independent"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            fields = ("transaction_id", "original_receipt_id", "reason", "amount", "currency", "return_location_id",
                      "requested_by_id", "idempotency_key", "request_fingerprint", "payment_plan")
            existing = RetailRefundRequest.all_objects.filter(tenant_id=self.tenant_id, pk=self.pk).values(*fields, "status").first()
            if existing and any(getattr(self, field) != existing[field] for field in fields):
                raise ValidationError("Refund request evidence cannot be edited; reject and create a corrected request.")
            if existing and existing["status"] in {self.Status.REJECTED, self.Status.COMPLETED}:
                raise ValidationError("A completed or rejected refund request cannot be changed.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Retail refund request evidence cannot be deleted.")


class RetailRefundLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("refund_request", "original_line", "inventory_batch")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    refund_request = models.ForeignKey(RetailRefundRequest, on_delete=models.PROTECT, related_name="lines")
    original_line = models.ForeignKey(PosTransactionLine, on_delete=models.PROTECT, related_name="refund_lines")
    quantity = models.DecimalField(**QUANTITY)
    amount = models.DecimalField(**MONEY)
    return_to_stock = models.BooleanField(default=False)
    inventory_batch = models.ForeignKey("inventory.InventoryBatch", on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    objects = RetailCashReceiptManager()
    all_objects = models.Manager.from_queryset(RetailCashReceiptQuerySet)()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["refund_request", "original_line"], name="uq_retail_refund_original_line"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="chk_retail_refund_line_qty"),
            models.CheckConstraint(condition=models.Q(amount__gte=0), name="chk_retail_refund_line_amount"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Retail refund line evidence is immutable; reject and create a corrected request.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Retail refund lines cannot be deleted.")


def retail_refund_number() -> str:
    return f"RFD-{uuid.uuid4().hex[:18].upper()}"


class RetailCashRefund(TenantConsistencyMixin, TimestampedModel):
    """Immutable cash outflow, linked to a receipt and the refund execution till."""

    tenant_relation_fields = ("refund_request", "original_receipt", "register", "register_session", "operator_shift", "created_by", "approved_by")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    refund_request = models.OneToOneField(RetailRefundRequest, on_delete=models.PROTECT, related_name="receipt")
    original_receipt = models.ForeignKey(RetailCashReceipt, on_delete=models.PROTECT, related_name="cash_refunds")
    refund_number = models.CharField(max_length=32, default=retail_refund_number)
    register = models.ForeignKey("pos_shift.PosRegister", on_delete=models.PROTECT, related_name="+")
    register_session = models.ForeignKey("pos_shift.RegisterSession", on_delete=models.PROTECT, related_name="+")
    operator_shift = models.ForeignKey("pos_shift.OperatorShift", on_delete=models.PROTECT, related_name="+")
    device_id = models.CharField(max_length=128)
    amount = models.DecimalField(**MONEY)
    cash_amount = models.DecimalField(default=None, **MONEY)
    payment_plan = models.JSONField(default=list)
    currency = models.CharField(max_length=3)
    lines_snapshot = models.JSONField(default=list)
    completed_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    idempotency_key = models.CharField(max_length=255)

    objects = RetailCashReceiptManager()
    all_objects = models.Manager.from_queryset(RetailCashReceiptQuerySet)()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "refund_number"], name="uq_retail_cash_refund_number"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uq_retail_cash_refund_key"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="chk_retail_cash_refund_positive"),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding and self.cash_amount is None:
            self.cash_amount = self.amount
        if self.pk and RetailCashRefund.all_objects.filter(tenant_id=self.tenant_id, pk=self.pk).exists():
            raise ValidationError("Retail cash refunds are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Retail cash refunds are immutable and cannot be deleted.")


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
