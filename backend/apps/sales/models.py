from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class PriceList(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        EXPIRED = "EXPIRED", "Expired"
        ARCHIVED = "ARCHIVED", "Archived"

    tenant_relation_fields = ()

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    currency = models.CharField(max_length=3, default="KES")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_pricelist_code")]

    def __str__(self):
        return f"{self.code} - {self.name}"


class PriceListEntry(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("price_list",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    price_list = models.ForeignKey(PriceList, on_delete=models.PROTECT, related_name="entries")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    minimum_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=1)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["price_list", "sku", "effective_from"], name="uq_pricelistentry_sku_date")
        ]

    def __str__(self):
        return f"{self.price_list.code} - {self.sku} - {self.unit_price}"


class CustomerPriceAgreement(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ()

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="price_agreements")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    agreed_price = models.DecimalField(max_digits=15, decimal_places=2)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "customer", "sku", "effective_from"], name="uq_customer_price_agreement"
            )
        ]

    def __str__(self):
        return f"{self.customer} - {self.sku} - {self.agreed_price}"


class PromotionRule(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("sku",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    sku = models.ForeignKey(
        "medicines.CommercialSKU",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    minimum_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=1)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uq_promotion_rule_code"),
            models.CheckConstraint(
                condition=Q(discount_percentage__gte=0, discount_percentage__lte=100),
                name="chk_promotion_discount_range",
            ),
            models.CheckConstraint(
                condition=Q(minimum_quantity__gt=0),
                name="chk_promotion_min_qty_positive",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Quotation(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        SENT = "SENT", "Sent"
        ACCEPTED = "ACCEPTED", "Accepted"
        CONVERTED = "CONVERTED", "Converted"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("branch", "sales_order", "customer", "delivery_address", "warehouse")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    quotation_number = models.CharField(max_length=64)
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="quotations")
    delivery_address = models.ForeignKey(
        "customers.CustomerDeliveryAddress", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    currency = models.CharField(max_length=3, default="KES")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    issue_date = models.DateField(auto_now_add=True)
    valid_until = models.DateField(null=True, blank=True)
    customer_reference = models.CharField(max_length=255, blank=True, default="")
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    notes = models.TextField(blank=True, default="")
    terms = models.TextField(blank=True, default="")
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    revision = models.IntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "quotation_number"], name="uq_quotation_number")]
        indexes = [
            models.Index(fields=["tenant", "status"], name="ix_quotation_status"),
            models.Index(fields=["tenant", "customer"], name="ix_quotation_customer"),
        ]

    def __str__(self):
        return self.quotation_number


class QuotationLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("quotation", "sku")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    description_snapshot = models.CharField(max_length=500, blank=True, default="")
    requested_quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit = models.CharField(max_length=50)
    package_conversion = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    base_unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    agreed_unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    line_subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="KES")
    price_list_ref = models.CharField(max_length=128, blank=True, default="")
    promotion_ref = models.CharField(max_length=128, blank=True, default="")
    override_reason = models.CharField(max_length=255, blank=True, default="")
    price_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    requested_delivery_date = models.DateField(null=True, blank=True)
    substitution_preference = models.CharField(max_length=64, blank=True, default="NO_SUBSTITUTION")
    notes = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(requested_quantity__gt=0), name="chk_quoteline_qty_positive")]

    def __str__(self):
        return f"{self.quotation.quotation_number} - {self.sku}"


class QuotationRevision(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("quotation",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.IntegerField()
    previous_revision = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changed_fields = models.JSONField(default=dict)
    previous_values = models.JSONField(default=dict)
    new_values = models.JSONField(default=dict)
    reason = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approval_status = models.CharField(max_length=32, default="PENDING")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["quotation", "revision_number"], name="uq_quotation_revision")]

    def __str__(self):
        return f"{self.quotation.quotation_number} - Rev {self.revision_number}"


class SalesOrder(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        APPROVED = "APPROVED", "Approved"
        RESERVED = "RESERVED", "Reserved"
        PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED", "Partially Allocated"
        ALLOCATED = "ALLOCATED", "Allocated"
        PARTIALLY_PICKED = "PARTIALLY_PICKED", "Partially Picked"
        PICKED = "PICKED", "Picked"
        PARTIALLY_PACKED = "PARTIALLY_PACKED", "Partially Packed"
        PACKED = "PACKED", "Packed"
        PARTIALLY_DISPATCHED = "PARTIALLY_DISPATCHED", "Partially Dispatched"
        DISPATCHED = "DISPATCHED", "Dispatched"
        PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED", "Partially Delivered"
        DELIVERED = "DELIVERED", "Delivered"
        CLOSED = "CLOSED", "Closed"
        REJECTED = "REJECTED", "Rejected"
        ON_HOLD = "ON_HOLD", "On Hold"
        BACKORDERED = "BACKORDERED", "Backordered"
        CANCELLED = "CANCELLED", "Cancelled"

    class FulfilmentPolicy(models.TextChoices):
        ALL_OR_NOTHING = "ALL_OR_NOTHING", "All or Nothing"
        ALLOW_PARTIAL = "ALLOW_PARTIAL", "Allow Partial"
        SPLIT_SHIPMENT = "SPLIT_SHIPMENT", "Split Shipment"
        BACKORDER_REMAINDER = "BACKORDER_REMAINDER", "Backorder Remainder"
        CANCEL_REMAINDER = "CANCEL_REMAINDER", "Cancel Remainder"

    class SubstitutionPolicy(models.TextChoices):
        NO_SUBSTITUTION = "NO_SUBSTITUTION", "No Substitution"
        EXACT_SKU_ONLY = "EXACT_SKU_ONLY", "Exact SKU Only"
        SAME_MANUFACTURED_PRODUCT = "SAME_MANUFACTURED_PRODUCT", "Same Manufactured Product"
        SAME_CLINICAL_PRODUCT = "SAME_CLINICAL_PRODUCT", "Same Clinical Product"
        SAME_SUBSTITUTION_GROUP = "SAME_SUBSTITUTION_GROUP", "Same Substitution Group"
        MANUAL_APPROVAL_REQUIRED = "MANUAL_APPROVAL_REQUIRED", "Manual Approval Required"

    class InvoicePolicy(models.TextChoices):
        ON_ORDER_APPROVAL = "ON_ORDER_APPROVAL", "On Order Approval"
        ON_DISPATCH = "ON_DISPATCH", "On Dispatch"
        ON_DELIVERY = "ON_DELIVERY", "On Delivery"
        ON_ACCEPTANCE = "ON_ACCEPTANCE", "On Acceptance"

    tenant_relation_fields = ("branch", "customer", "delivery_address", "source_quotation")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="sales_orders")
    order_number = models.CharField(max_length=64)
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    source_quotation = models.ForeignKey(
        Quotation, null=True, blank=True, on_delete=models.PROTECT, related_name="sales_orders"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="sales_orders")
    delivery_address = models.ForeignKey(
        "customers.CustomerDeliveryAddress", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    customer_po_reference = models.CharField(max_length=128, blank=True, default="")
    currency = models.CharField(max_length=3, default="KES")
    order_date = models.DateField(auto_now_add=True)
    requested_delivery_date = models.DateField(null=True, blank=True)
    priority = models.IntegerField(default=0)
    fulfilment_policy = models.CharField(
        max_length=64, choices=FulfilmentPolicy.choices, default=FulfilmentPolicy.ALLOW_PARTIAL
    )
    substitution_policy = models.CharField(
        max_length=64, choices=SubstitutionPolicy.choices, default=SubstitutionPolicy.NO_SUBSTITUTION
    )
    invoice_policy = models.CharField(max_length=64, choices=InvoicePolicy.choices, default=InvoicePolicy.ON_DISPATCH)
    payment_terms_snapshot = models.CharField(max_length=128, blank=True, default="")
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    hold_reason = models.TextField(blank=True, default="")
    cancellation_reason = models.TextField(blank=True, default="")
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "order_number"], name="uq_sales_order_number"),
            models.CheckConstraint(condition=Q(subtotal__gte=0), name="chk_salesorder_subtotal_nonneg"),
            models.CheckConstraint(condition=Q(tax_total__gte=0), name="chk_salesorder_tax_nonneg"),
            models.CheckConstraint(condition=Q(total__gte=0), name="chk_salesorder_total_nonneg"),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="ix_salesorder_status"),
            models.Index(fields=["tenant", "customer"], name="ix_salesorder_customer"),
        ]

    def __str__(self):
        return self.order_number


class SalesOrderLine(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        RESERVED = "RESERVED", "Reserved"
        ALLOCATED = "ALLOCATED", "Allocated"
        PICKING = "PICKING", "Picking"
        PICKED = "PICKED", "Picked"
        PACKED = "PACKED", "Packed"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"
        BACKORDERED = "BACKORDERED", "Backordered"

    tenant_relation_fields = ("sales_order", "sku")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    description_snapshot = models.CharField(max_length=500, blank=True, default="")
    requested_quantity = models.DecimalField(max_digits=15, decimal_places=4)
    approved_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    cancelled_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    reserved_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    allocated_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    picked_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    packed_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    dispatched_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    delivered_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    returned_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    backordered_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    unit = models.CharField(max_length=50)
    package_conversion = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    base_unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    agreed_unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    line_subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="KES")
    price_list_ref = models.CharField(max_length=128, blank=True, default="")
    promotion_ref = models.CharField(max_length=128, blank=True, default="")
    override_reason = models.CharField(max_length=255, blank=True, default="")
    price_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    substitution_preference = models.CharField(max_length=64, blank=True, default="NO_SUBSTITUTION")
    requested_batch_constraints = models.JSONField(default=dict, blank=True)
    minimum_shelf_life_days = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True)
    reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(requested_quantity__gt=0), name="chk_soline_req_qty_positive"),
            models.CheckConstraint(condition=Q(approved_quantity__gte=0), name="chk_soline_approved_nonneg"),
            models.CheckConstraint(condition=Q(cancelled_quantity__gte=0), name="chk_soline_cancelled_nonneg"),
            models.CheckConstraint(condition=Q(reserved_quantity__gte=0), name="chk_soline_reserved_nonneg"),
            models.CheckConstraint(condition=Q(allocated_quantity__gte=0), name="chk_soline_allocated_nonneg"),
            models.CheckConstraint(condition=Q(picked_quantity__gte=0), name="chk_soline_picked_nonneg"),
            models.CheckConstraint(condition=Q(packed_quantity__gte=0), name="chk_soline_packed_nonneg"),
            models.CheckConstraint(condition=Q(dispatched_quantity__gte=0), name="chk_soline_dispatched_nonneg"),
            models.CheckConstraint(condition=Q(delivered_quantity__gte=0), name="chk_soline_delivered_nonneg"),
            models.CheckConstraint(condition=Q(returned_quantity__gte=0), name="chk_soline_returned_nonneg"),
            models.CheckConstraint(condition=Q(backordered_quantity__gte=0), name="chk_soline_backorder_nonneg"),
            models.CheckConstraint(
                condition=Q(package_conversion__gt=0), name="chk_soline_package_conversion_positive"
            ),
            models.CheckConstraint(condition=Q(line_subtotal__gte=0), name="chk_soline_subtotal_nonneg"),
            models.CheckConstraint(condition=Q(tax_amount__gte=0), name="chk_soline_tax_nonneg"),
            models.CheckConstraint(condition=Q(line_total__gte=0), name="chk_soline_total_nonneg"),
            models.CheckConstraint(
                condition=Q(approved_quantity__lte=F("requested_quantity")), name="chk_soline_approved_lte_requested"
            ),
            models.CheckConstraint(
                condition=Q(cancelled_quantity__lte=F("requested_quantity")), name="chk_soline_cancelled_lte_requested"
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__lte=F("approved_quantity")), name="chk_soline_reserved_lte_approved"
            ),
            models.CheckConstraint(
                condition=Q(allocated_quantity__lte=F("reserved_quantity")), name="chk_soline_allocated_lte_reserved"
            ),
            models.CheckConstraint(
                condition=Q(picked_quantity__lte=F("allocated_quantity")), name="chk_soline_picked_lte_allocated"
            ),
            models.CheckConstraint(
                condition=Q(packed_quantity__lte=F("picked_quantity")), name="chk_soline_packed_lte_picked"
            ),
            models.CheckConstraint(
                condition=Q(dispatched_quantity__lte=F("packed_quantity")), name="chk_soline_dispatched_lte_packed"
            ),
            models.CheckConstraint(
                condition=Q(delivered_quantity__lte=F("dispatched_quantity")),
                name="chk_soline_delivered_lte_dispatched",
            ),
            models.CheckConstraint(
                condition=Q(returned_quantity__lte=F("delivered_quantity")), name="chk_soline_returned_lte_delivered"
            ),
        ]

    def __str__(self):
        return f"{self.sales_order.order_number} - {self.sku}"


class SalesOrderHold(TenantConsistencyMixin, TimestampedModel):
    class HoldType(models.TextChoices):
        CREDIT = "CREDIT", "Credit"
        COMPLIANCE = "COMPLIANCE", "Compliance"
        CUSTOMER = "CUSTOMER", "Customer"
        PRICING = "PRICING", "Pricing"
        INVENTORY = "INVENTORY", "Inventory"
        QUALITY = "QUALITY", "Quality"
        RECALL = "RECALL", "Recall"
        DELIVERY = "DELIVERY", "Delivery"
        MANUAL_REVIEW = "MANUAL_REVIEW", "Manual Review"

    tenant_relation_fields = ("sales_order",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="holds")
    hold_type = models.CharField(max_length=32, choices=HoldType.choices)
    reason = models.TextField()
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    placed_at = models.DateTimeField(auto_now_add=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.TextField(blank=True, default="")
    supporting_document = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["sales_order", "is_active"], name="ix_hold_active")]

    def __str__(self):
        return f"Hold {self.hold_type} on {self.sales_order.order_number}"


class SalesOrderAllocation(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        ALLOCATED = "ALLOCATED", "Allocated"
        PICKING = "PICKING", "Picking"
        PICKED = "PICKED", "Picked"
        PACKED = "PACKED", "Packed"
        DISPATCHED = "DISPATCHED", "Dispatched"
        RELEASED = "RELEASED", "Released"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("sales_order_line",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.CASCADE, related_name="allocations")
    inventory_reservation = models.ForeignKey(
        "inventory.InventoryReservation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    inventory_batch = models.ForeignKey("inventory.InventoryBatch", on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(
        "inventory.InventoryLocation", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    expiry_date = models.DateField(null=True, blank=True)
    allocation_timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ALLOCATED)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sales_order_line", "inventory_batch", "location"], name="uq_allocation_line_batch_loc"
            )
        ]

    def __str__(self):
        return f"Alloc: {self.sales_order_line} - {self.inventory_batch}"


class SubstitutionProposal(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposed"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("sales_order_line", "requested_sku", "proposed_sku")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    sales_order_line = models.ForeignKey(
        SalesOrderLine, on_delete=models.CASCADE, related_name="substitution_proposals"
    )
    requested_sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    proposed_sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    substitution_group = models.CharField(max_length=128, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    price_variance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    customer_consent = models.BooleanField(default=False)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PROPOSED)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"Subst: {self.requested_sku} -> {self.proposed_sku}"


class PickingWave(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        RELEASED = "RELEASED", "Released"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("branch",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    wave_number = models.CharField(max_length=64)
    scope = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "wave_number"], name="uq_picking_wave_number")]

    def __str__(self):
        return self.wave_number


class PickingTask(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        PICKED = "PICKED", "Picked"
        VERIFIED = "VERIFIED", "Verified"
        SHORT_PICK = "SHORT_PICK", "Short Pick"
        BLOCKED = "BLOCKED", "Blocked"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = (
        "picking_wave",
        "sales_order",
        "sales_order_line",
        "allocation",
        "source_location",
        "sku",
        "batch",
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    picking_wave = models.ForeignKey(
        PickingWave, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="picking_tasks")
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, related_name="picking_tasks")
    allocation = models.ForeignKey(
        SalesOrderAllocation, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    source_location = models.ForeignKey("inventory.InventoryLocation", on_delete=models.PROTECT, related_name="+")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        "inventory.InventoryBatch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    requested_quantity = models.DecimalField(max_digits=15, decimal_places=4)
    picked_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    short_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True)
    assigned_picker = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    exception_reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(requested_quantity__gt=0), name="chk_picktask_qty_positive"),
            models.CheckConstraint(condition=Q(picked_quantity__gte=0), name="chk_picktask_picked_nonneg"),
            models.CheckConstraint(condition=Q(short_quantity__gte=0), name="chk_picktask_short_nonneg"),
            models.CheckConstraint(
                condition=Q(requested_quantity__gte=F("picked_quantity") + F("short_quantity")),
                name="chk_picktask_reconciliation",
            ),
        ]

    def __str__(self):
        return f"Task for {self.sales_order.order_number} - {self.sku}"


class PackingSession(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PACKING = "PACKING", "Packing"
        VERIFIED = "VERIFIED", "Verified"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("branch", "sales_order")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    session_number = models.CharField(max_length=64)
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="packing_sessions")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    packer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verifier = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "session_number"], name="uq_packing_session_number")]

    def __str__(self):
        return self.session_number


class Package(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PACKING = "PACKING", "Packing"
        VERIFIED = "VERIFIED", "Verified"
        SEALED = "SEALED", "Sealed"
        READY_FOR_DISPATCH = "READY_FOR_DISPATCH", "Ready for Dispatch"
        REOPENED = "REOPENED", "Reopened"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("packing_session", "sales_order", "delivery_address")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    packing_session = models.ForeignKey(PackingSession, on_delete=models.CASCADE, related_name="packages")
    package_number = models.CharField(max_length=64)
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="packages")
    delivery_address = models.ForeignKey(
        "customers.CustomerDeliveryAddress", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    temperature_zone = models.CharField(max_length=32, blank=True, default="AMBIENT")
    package_type = models.CharField(max_length=64, blank=True, default="")
    seal_number = models.CharField(max_length=128, blank=True, default="")
    gross_weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    dimensions = models.CharField(max_length=64, blank=True, default="")
    packer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verifier = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    packed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "package_number"], name="uq_package_number")]

    def __str__(self):
        return self.package_number


class PackageLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("package", "sales_order_line", "picking_task", "sku", "batch")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="lines")
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, related_name="+")
    picking_task = models.ForeignKey(PickingTask, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        "inventory.InventoryBatch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit = models.CharField(max_length=50)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["package", "sales_order_line", "batch"], name="uq_packageline_sol_batch"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="chk_packageline_qty_positive"),
        ]

    def __str__(self):
        return f"{self.package.package_number} - {self.sku}"


class DispatchOrder(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        READY = "READY", "Ready"
        APPROVED = "APPROVED", "Approved"
        LOADED = "LOADED", "Loaded"
        DISPATCHED = "DISPATCHED", "Dispatched"
        IN_TRANSIT = "IN_TRANSIT", "In Transit"
        PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED", "Partially Delivered"
        DELIVERED = "DELIVERED", "Delivered"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"
        FAILED = "FAILED", "Failed"
        RETURNED = "RETURNED", "Returned"

    tenant_relation_fields = ("branch", "customer", "delivery_address")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    dispatch_number = models.CharField(max_length=64)
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    sales_order = models.ForeignKey(
        SalesOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="dispatches",
    )
    warehouse = models.ForeignKey(
        "inventory.InventoryLocation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="dispatches")
    delivery_address = models.ForeignKey(
        "customers.CustomerDeliveryAddress", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    carrier = models.CharField(max_length=128, blank=True, default="")
    vehicle = models.CharField(max_length=64, blank=True, default="")
    driver = models.CharField(max_length=128, blank=True, default="")
    temperature_requirement = models.CharField(max_length=32, blank=True, default="AMBIENT")
    dispatch_date = models.DateField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "dispatch_number"], name="uq_dispatch_number")]

    def __str__(self):
        return self.dispatch_number


class DispatchLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("dispatch_order", "sales_order_line", "source_location", "sku", "batch")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    dispatch_order = models.ForeignKey(DispatchOrder, on_delete=models.CASCADE, related_name="lines")
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, related_name="dispatch_lines")
    package = models.ForeignKey(Package, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    source_location = models.ForeignKey(
        "inventory.InventoryLocation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        "inventory.InventoryBatch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit = models.CharField(max_length=50)
    idempotency_key = models.CharField(max_length=255, unique=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dispatch_order", "sales_order_line", "batch"], name="uq_dispatchline_sol_batch"
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="chk_dispatchline_qty_positive"),
        ]

    def __str__(self):
        return f"{self.dispatch_order.dispatch_number} - {self.sku}"


class DispatchPackage(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("dispatch_order", "package")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    dispatch_order = models.ForeignKey(DispatchOrder, on_delete=models.CASCADE, related_name="dispatch_packages")
    package = models.ForeignKey(Package, on_delete=models.PROTECT, related_name="dispatches")
    loaded_at = models.DateTimeField(null=True, blank=True)
    loaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dispatch_order", "package"],
                name="uq_dispatch_package",
            )
        ]

    def __str__(self):
        return f"{self.dispatch_order.dispatch_number} - {self.package.package_number}"


class DeliveryRecord(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for Delivery"
        PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED", "Partially Delivered"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Failed"
        REFUSED = "REFUSED", "Refused"
        RETURN_TO_DEPOT = "RETURN_TO_DEPOT", "Return to Depot"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("dispatch_order", "customer", "delivery_address")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    dispatch_order = models.ForeignKey(DispatchOrder, on_delete=models.PROTECT, related_name="deliveries")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    delivery_address = models.ForeignKey(
        "customers.CustomerDeliveryAddress", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    delivered_at = models.DateTimeField(null=True, blank=True)
    recipient_name = models.CharField(max_length=255, blank=True, default="")
    recipient_role = models.CharField(max_length=128, blank=True, default="")
    recipient_phone = models.CharField(max_length=64, blank=True, default="")
    proof_type = models.CharField(max_length=64, blank=True, default="")
    signature_ref = models.CharField(max_length=255, blank=True, default="")
    photo_ref = models.CharField(max_length=255, blank=True, default="")
    coordinates = models.CharField(max_length=64, blank=True, default="")
    temperature_evidence = models.TextField(blank=True, default="")
    delivery_notes = models.TextField(blank=True, default="")
    failure_reason = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=255, blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="uq_delivery_idempotency",
            )
        ]

    def __str__(self):
        return f"Delivery for {self.dispatch_order.dispatch_number}"


class DeliveryLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("delivery_record", "dispatch_line", "sales_order_line", "sku", "batch")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    delivery_record = models.ForeignKey(DeliveryRecord, on_delete=models.CASCADE, related_name="lines")
    dispatch_line = models.ForeignKey(DispatchLine, on_delete=models.PROTECT, related_name="+")
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, related_name="delivery_lines")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        "inventory.InventoryBatch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    dispatched_quantity = models.DecimalField(max_digits=15, decimal_places=4)
    accepted_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    rejected_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    damaged_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    missing_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    return_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["delivery_record", "dispatch_line"],
                name="uq_delivery_dispatch_line",
            ),
            models.CheckConstraint(condition=Q(dispatched_quantity__gt=0), name="chk_delivery_dispatched_positive"),
            models.CheckConstraint(condition=Q(accepted_quantity__gte=0), name="chk_delivery_accepted_nonneg"),
            models.CheckConstraint(condition=Q(rejected_quantity__gte=0), name="chk_delivery_rejected_nonneg"),
            models.CheckConstraint(condition=Q(damaged_quantity__gte=0), name="chk_delivery_damaged_nonneg"),
            models.CheckConstraint(condition=Q(missing_quantity__gte=0), name="chk_delivery_missing_nonneg"),
            models.CheckConstraint(condition=Q(return_quantity__gte=0), name="chk_delivery_return_nonneg"),
            models.CheckConstraint(
                condition=Q(
                    dispatched_quantity__gte=(
                        F("accepted_quantity") + F("rejected_quantity") + F("damaged_quantity") + F("missing_quantity")
                    )
                ),
                name="chk_delivery_line_reconciliation",
            ),
        ]

    def __str__(self):
        return f"Del Line for {self.delivery_record} - {self.sku}"


class SalesReturnAuthorization(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        APPROVED = "APPROVED", "Approved"
        AWAITING_RETURN = "AWAITING_RETURN", "Awaiting Return"
        RECEIVED = "RECEIVED", "Received"
        INSPECTED = "INSPECTED", "Inspected"
        ACCEPTED = "ACCEPTED", "Accepted"
        CLOSED = "CLOSED", "Closed"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("sales_order", "customer")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    return_number = models.CharField(max_length=64)
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="returns")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    reason = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    idempotency_key = models.CharField(max_length=255, blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "return_number"], name="uq_return_number"),
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="uq_sales_return_idempotency",
            ),
        ]

    def __str__(self):
        return self.return_number


class SalesReturnLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("return_authorization", "sales_order_line", "sku", "batch")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    return_authorization = models.ForeignKey(SalesReturnAuthorization, on_delete=models.CASCADE, related_name="lines")
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, related_name="return_lines")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        "inventory.InventoryBatch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    condition = models.CharField(max_length=64, blank=True, default="")
    temperature_evidence = models.TextField(blank=True, default="")
    expiry_check = models.BooleanField(default=False)
    recall_context = models.CharField(max_length=255, blank=True, default="")
    return_eligibility = models.CharField(max_length=64, blank=True, default="")
    quality_disposition = models.CharField(max_length=64, blank=True, default="")
    received_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="chk_returnline_qty_positive"),
            models.CheckConstraint(condition=Q(received_quantity__gte=0), name="chk_returnline_received_nonneg"),
            models.CheckConstraint(
                condition=Q(received_quantity__lte=F("quantity")), name="chk_returnline_received_lte_authorized"
            ),
        ]

    def __str__(self):
        return f"{self.return_authorization.return_number} - {self.sku}"
