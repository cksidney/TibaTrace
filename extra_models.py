class InventoryReservation(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ALLOCATED = "ALLOCATED", "Allocated"
        PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED", "Partially Fulfilled"
        FULFILLED = "FULFILLED", "Fulfilled"
        RELEASED = "RELEASED", "Released"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("branch", "source_location", "sku", "batch")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    source_location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT, related_name="reservations")
    
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(InventoryBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    
    requested_quantity = models.DecimalField(max_digits=15, decimal_places=4)
    allocated_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    unit = models.CharField(max_length=50)
    
    purpose = models.CharField(max_length=100)
    source_document = models.CharField(max_length=255, blank=True)
    
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.PENDING)
    priority = models.IntegerField(default=1)
    
    expiry_time = models.DateTimeField(null=True, blank=True)
    actor = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(check=Q(requested_quantity__gt=0), name="chk_reservation_req_qty_positive"),
            models.CheckConstraint(check=Q(allocated_quantity__gte=0), name="chk_reservation_alloc_qty_nonneg"),
        ]

class StockTransfer(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        ALLOCATED = "ALLOCATED", "Allocated"
        DISPATCHED = "DISPATCHED", "Dispatched"
        IN_TRANSIT = "IN_TRANSIT", "In Transit"
        PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED", "Partially Received"
        RECEIVED = "RECEIVED", "Received"
        CLOSED = "CLOSED", "Closed"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
        LOST = "LOST", "Lost"
        DAMAGED = "DAMAGED", "Damaged"

    tenant_relation_fields = ("source_branch", "destination_branch", "source_location", "destination_location")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    
    transfer_number = models.CharField(max_length=100)
    
    source_branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="outbound_transfers")
    destination_branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="inbound_transfers")
    
    source_location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT, related_name="outbound_transfers")
    destination_location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT, related_name="inbound_transfers")
    
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.DRAFT)
    
    requested_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    approved_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    dispatched_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    received_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    
    dispatch_timestamp = models.DateTimeField(null=True, blank=True)
    receipt_timestamp = models.DateTimeField(null=True, blank=True)
    
    reason = models.TextField(blank=True)
    document_reference = models.CharField(max_length=255, blank=True)
    
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "transfer_number"], name="uq_stock_transfer_number")
        ]

class StockTransferLine(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("transfer", "sku", "batch")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(InventoryBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    
    requested_quantity = models.DecimalField(max_digits=15, decimal_places=4)
    allocated_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    dispatched_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    received_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    rejected_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    damaged_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    
    unit = models.CharField(max_length=50)
    discrepancy_reason = models.TextField(blank=True)
    
    objects = StrictTenantManager()
    all_objects = models.Manager()

class StocktakeSession(TenantConsistencyMixin, TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SCHEDULED = "SCHEDULED", "Scheduled"
        OPEN = "OPEN", "Open"
        COUNTING = "COUNTING", "Counting"
        REVIEW = "REVIEW", "Review"
        APPROVED = "APPROVED", "Approved"
        POSTED = "POSTED", "Posted"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("branch",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    
    locations = models.ManyToManyField(InventoryLocation, related_name="stocktake_sessions")
    scope = models.CharField(max_length=100) # e.g. "FULL", "PARTIAL", "CYCLE"
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.DRAFT)
    
    freeze_policy = models.CharField(max_length=50, default="NONE") # "NONE", "BLOCK_ALL", "WARN"
    
    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    counted_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    approved_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    
    variance_threshold = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    document_number = models.CharField(max_length=100, blank=True)
    
    objects = StrictTenantManager()
    all_objects = models.Manager()

class StocktakeCount(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("session", "sku", "batch", "location")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    session = models.ForeignKey(StocktakeSession, on_delete=models.CASCADE, related_name="counts")
    
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(InventoryBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT, related_name="+")
    
    expected_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    counted_quantity = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    variance = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    
    first_count = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    recount = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    final_approved_count = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    
    reason = models.TextField(blank=True)
    counter = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    timestamp = models.DateTimeField(null=True, blank=True)
    
    objects = StrictTenantManager()
    all_objects = models.Manager()
