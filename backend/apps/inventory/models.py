import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import StrictTenantManager, StrictTenantQuerySet, TenantConsistencyMixin, TimestampedModel


class InventoryLocation(TenantConsistencyMixin, TimestampedModel):
    class LocationType(models.TextChoices):
        WAREHOUSE = "WAREHOUSE", "Warehouse"
        STORE = "STORE", "Store"
        PHARMACY = "PHARMACY", "Pharmacy"
        DISPENSARY = "DISPENSARY", "Dispensary"
        RECEIVING = "RECEIVING", "Receiving"
        QUARANTINE = "QUARANTINE", "Quarantine"
        COLD_ROOM = "COLD_ROOM", "Cold Room"
        FREEZER = "FREEZER", "Freezer"
        CONTROLLED_VAULT = "CONTROLLED_VAULT", "Controlled Vault"
        PICKING = "PICKING", "Picking"
        RETURNS = "RETURNS", "Returns"
        DAMAGED = "DAMAGED", "Damaged"
        EXPIRED = "EXPIRED", "Expired"
        TRANSIT = "TRANSIT", "Transit"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        CLOSED = "CLOSED", "Closed"

    tenant_relation_fields = ("branch",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="inventory_locations")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="inventory_locations")
    parent_location = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="sub_locations")
    
    location_code = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    location_type = models.CharField(max_length=50, choices=LocationType.choices, default=LocationType.STORE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    
    # Capabilities
    restricted_flag = models.BooleanField(default=False)
    cold_chain_capability = models.BooleanField(default=False)
    controlled_drug_capability = models.BooleanField(default=False)
    quarantine_capability = models.BooleanField(default=False)
    returns_capability = models.BooleanField(default=False)
    damaged_goods_capability = models.BooleanField(default=False)
    expiry_hold_capability = models.BooleanField(default=False)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "branch", "location_code"], name="uq_inventory_loc_code_per_branch")
        ]

    def __str__(self):
        return f"{self.name} ({self.location_code})"


class InventoryBatch(TenantConsistencyMixin, TimestampedModel):
    class QualityStatus(models.TextChoices):
        RELEASED = "RELEASED", "Released"
        QUARANTINED = "QUARANTINED", "Quarantined"
        REJECTED = "REJECTED", "Rejected"
        DAMAGED = "DAMAGED", "Damaged"
        EXPIRED = "EXPIRED", "Expired"

    class RecallStatus(models.TextChoices):
        NONE = "NONE", "None"
        HOLD = "HOLD", "Hold"
        RECALLED = "RECALLED", "Recalled"

    tenant_relation_fields = ("sku", "manufactured_product", "source_received_batch")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="inventory_batches")
    manufactured_product = models.ForeignKey("medicines.ManufacturedMedicinalProduct", on_delete=models.PROTECT, related_name="+")
    
    # Not all inventory batches may have a procurement source (e.g. initial stocktake), but usually they do
    source_received_batch = models.ForeignKey("procurement.ReceivedBatch", on_delete=models.PROTECT, null=True, blank=True, related_name="inventory_batches")
    
    manufacturer_batch_number = models.CharField(max_length=100)
    manufacture_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField()
    
    quality_status = models.CharField(max_length=20, choices=QualityStatus.choices, default=QualityStatus.RELEASED)
    recall_status = models.CharField(max_length=20, choices=RecallStatus.choices, default=RecallStatus.NONE)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            # In a real environment, manufacturer_batch_number is unique per manufactured product
            models.UniqueConstraint(fields=["tenant", "manufactured_product", "manufacturer_batch_number"], name="uq_inventory_batch_number")
        ]


class InventoryLedgerEntryQuerySet(StrictTenantQuerySet):
    def update(self, **kwargs):
        raise ValidationError("InventoryLedgerEntry records are immutable and cannot be updated.")
        
    def delete(self):
        raise ValidationError("InventoryLedgerEntry records are immutable and cannot be deleted.")

class InventoryLedgerEntryManager(StrictTenantManager):
    def _base_queryset(self):
        return InventoryLedgerEntryQuerySet(self.model, using=self._db)

class InventoryLedgerEntry(TenantConsistencyMixin, TimestampedModel):
    class EntryType(models.TextChoices):
        RECEIPT = "RECEIPT", "Receipt"
        TRANSFER_OUT = "TRANSFER_OUT", "Transfer Out"
        TRANSFER_IN = "TRANSFER_IN", "Transfer In"
        RESERVATION = "RESERVATION", "Reservation"
        RESERVATION_RELEASE = "RESERVATION_RELEASE", "Reservation Release"
        ISSUE = "ISSUE", "Issue"
        RETURN_IN = "RETURN_IN", "Return In"
        RETURN_OUT = "RETURN_OUT", "Return Out"
        ADJUSTMENT_INCREASE = "ADJUSTMENT_INCREASE", "Adjustment Increase"
        ADJUSTMENT_DECREASE = "ADJUSTMENT_DECREASE", "Adjustment Decrease"
        STOCKTAKE_GAIN = "STOCKTAKE_GAIN", "Stocktake Gain"
        STOCKTAKE_LOSS = "STOCKTAKE_LOSS", "Stocktake Loss"
        DAMAGE = "DAMAGE", "Damage"
        EXPIRY = "EXPIRY", "Expiry"
        RECALL_HOLD = "RECALL_HOLD", "Recall Hold"
        RECALL_RELEASE = "RECALL_RELEASE", "Recall Release"
        QUARANTINE = "QUARANTINE", "Quarantine"
        QUALITY_RELEASE = "QUALITY_RELEASE", "Quality Release"
        WRITE_OFF = "WRITE_OFF", "Write Off"
        DESTRUCTION = "DESTRUCTION", "Destruction"
        REVERSAL = "REVERSAL", "Reversal"

    tenant_relation_fields = ("branch", "location", "inventory_batch", "sku")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT, related_name="ledger_entries")
    
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    inventory_batch = models.ForeignKey(InventoryBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="ledger_entries")
    
    entry_type = models.CharField(max_length=40, choices=EntryType.choices)
    
    # Delta (positive for increase, negative for decrease)
    quantity_delta = models.DecimalField(max_digits=15, decimal_places=4)
    unit = models.CharField(max_length=50) # The unit used (e.g. 'box', 'tablet')
    base_quantity_delta = models.DecimalField(max_digits=15, decimal_places=4) # Normalized to base unit
    
    transaction_timestamp = models.DateTimeField(auto_now_add=True)
    effective_timestamp = models.DateTimeField()
    
    source_document_type = models.CharField(max_length=100)
    source_document_id = models.CharField(max_length=255)
    source_line_id = models.CharField(max_length=255, null=True, blank=True)
    
    correlation_id = models.UUIDField(default=uuid.uuid4)
    idempotency_key = models.CharField(max_length=255)
    
    actor = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    reason_code = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    
    reversal_reference = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by")
    
    objects = InventoryLedgerEntryManager()
    all_objects = models.Manager.from_queryset(InventoryLedgerEntryQuerySet)()

    class Meta:
        ordering = ["-transaction_timestamp"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uq_ledger_idempotency"),
            models.CheckConstraint(condition=~Q(quantity_delta=0), name="chk_ledger_delta_nonzero"),
            models.CheckConstraint(condition=~Q(base_quantity_delta=0), name="chk_ledger_base_delta_nonzero")
        ]
        indexes = [
            models.Index(fields=["tenant", "sku", "location", "inventory_batch"], name="ix_ledger_sku_loc_batch"),
            models.Index(fields=["tenant", "transaction_timestamp"], name="ix_ledger_timestamp")
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            # Check if it actually exists in DB
            if InventoryLedgerEntry.all_objects.filter(pk=self.pk, tenant=self.tenant_id).exists():
                raise ValidationError("InventoryLedgerEntry records are immutable and cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("InventoryLedgerEntry records are immutable and cannot be deleted.")


class InventoryBalance(TenantConsistencyMixin, TimestampedModel):
    """
    Balance projection updated by the ledger service.
    Authoritative quantity comes from SUM(InventoryLedgerEntry), but this is cached for speed.
    """
    tenant_relation_fields = ("branch", "location", "sku", "inventory_batch")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT, related_name="balances")
    
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="balances")
    inventory_batch = models.ForeignKey(InventoryBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="balances")
    
    quality_status = models.CharField(max_length=20, choices=InventoryBatch.QualityStatus.choices)
    expiry_status = models.CharField(max_length=20, default="NORMAL") # NORMAL, NEAR_EXPIRY, EXPIRED
    
    # Base unit measures
    on_hand = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    reserved = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    quarantined = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    damaged = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    expired = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    recalled = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    in_transit = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    # derived: available = on_hand - reserved - quarantined - damaged - expired - recalled
    available = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    
    last_calculated_at = models.DateTimeField(auto_now=True)
    
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "location", "sku", "inventory_batch", "quality_status", "expiry_status"],
                name="uq_inventory_balance_dimensions"
            ),
            models.CheckConstraint(check=Q(on_hand__gte=0), name="chk_balance_on_hand_nonneg"),
            models.CheckConstraint(check=Q(reserved__gte=0), name="chk_balance_reserved_nonneg"),
            models.CheckConstraint(check=Q(available__gte=0), name="chk_balance_available_nonneg"),
        ]


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


# ==============================================================================
# EXTENDED WAREHOUSE & BARCODE MODELS
# ==============================================================================

class WarehouseTask(TenantConsistencyMixin, TimestampedModel):
    class TaskType(models.TextChoices):
        RECEIVE = "RECEIVE", "Receive"
        INSPECT = "INSPECT", "Inspect"
        PUTAWAY = "PUTAWAY", "Putaway"
        PICK = "PICK", "Pick"
        PACK = "PACK", "Pack"
        DISPATCH = "DISPATCH", "Dispatch"
        TRANSFER_RECEIVE = "TRANSFER_RECEIVE", "Transfer Receive"
        REPLENISH = "REPLENISH", "Replenish"
        COUNT = "COUNT", "Count"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("branch", "location", "sku")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    task_type = models.CharField(max_length=50, choices=TaskType.choices, default=TaskType.PICK)
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.PENDING)
    priority = models.IntegerField(default=1)
    assigned_user = models.ForeignKey("identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    batch = models.ForeignKey(InventoryBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class BarcodeMaster(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("sku",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.CASCADE, related_name="barcodes")
    barcode = models.CharField(max_length=128, db_index=True)
    barcode_type = models.CharField(max_length=64, default="GS1_128")
    pack_conversion = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "barcode"], name="uq_barcode_master")
        ]


class ReplenishmentRecommendation(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("branch", "sku")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.CASCADE, related_name="+")
    recommended_quantity = models.DecimalField(max_digits=15, decimal_places=4)
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, default="PENDING")

    objects = StrictTenantManager()
    all_objects = models.Manager()

