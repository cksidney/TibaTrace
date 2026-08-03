import decimal
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel
from apps.medicines.models import CommercialSKU
from apps.organizations.models import Location


class Supplier(TimestampedModel):
    """
    Commercial supplier counterparty distinct from manufacturer and tenant.
    """

    class Status(models.TextChoices):
        PROSPECTIVE = "PROSPECTIVE", "Prospective"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        APPROVED = "APPROVED", "Approved"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        DISQUALIFIED = "DISQUALIFIED", "Disqualified"
        ARCHIVED = "ARCHIVED", "Archived"

    class RiskCategory(models.TextChoices):
        LOW = "LOW", "Low Risk"
        MEDIUM = "MEDIUM", "Medium Risk"
        HIGH = "HIGH", "High Risk"
        CRITICAL = "CRITICAL", "Critical Risk"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="suppliers")
    supplier_code = models.CharField(max_length=64, db_index=True)
    legal_name = models.CharField(max_length=255)
    trading_name = models.CharField(max_length=255, blank=True, default="")
    registration_number = models.CharField(max_length=128, blank=True, default="")
    tax_identifier = models.CharField(max_length=128, blank=True, default="")
    country = models.CharField(max_length=100, default="Kenya")
    address = models.TextField(blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=64, blank=True, default="")
    payment_terms = models.CharField(max_length=128, default="NET30")
    default_currency = models.CharField(max_length=3, default="KES")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PROSPECTIVE, db_index=True)
    risk_category = models.CharField(max_length=32, choices=RiskCategory.choices, default=RiskCategory.MEDIUM)
    suspension_reason = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_suppliers"
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "supplier_code"], name="unique_tenant_supplier_code")
        ]

    def __str__(self):
        return f"{self.legal_name} [{self.supplier_code}]"


class SupplierQualification(TimestampedModel):
    """
    Structured qualification evidence and licences for suppliers.
    """

    class QualificationType(models.TextChoices):
        BUSINESS_REGISTRATION = "BUSINESS_REGISTRATION", "Business Registration"
        TAX_COMPLIANCE = "TAX_COMPLIANCE", "Tax Compliance Certificate"
        WHOLESALE_DEALER_LICENCE = "WHOLESALE_DEALER_LICENCE", "Wholesale Dealer Licence"
        GDP_CERTIFICATE = "GDP_CERTIFICATE", "Good Distribution Practice Certificate"
        QUALITY_AGREEMENT = "QUALITY_AGREEMENT", "Quality Agreement"
        COLD_CHAIN_AUTHORIZATION = "COLD_CHAIN_AUTHORIZATION", "Cold-Chain Authorization"
        CONTROLLED_DRUG_LICENCE = "CONTROLLED_DRUG_LICENCE", "Controlled Drug Licence"

    class QualificationVerificationStatus(models.TextChoices):
        PENDING = "PENDING", "Pending Verification"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="supplier_qualifications")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="qualifications")
    qualification_type = models.CharField(max_length=64, choices=QualificationType.choices)
    licence_number = models.CharField(max_length=128)
    issuing_authority = models.CharField(max_length=255, blank=True, default="")
    effective_date = models.DateField()
    expiry_date = models.DateField()
    verification_status = models.CharField(
        max_length=32, choices=QualificationVerificationStatus.choices, default=QualificationVerificationStatus.PENDING, db_index=True
    )
    document_reference = models.CharField(max_length=255, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="verified_qualifications"
    )
    #: Who put the qualification forward. Required for segregation of duties:
    #: without it, "the reviewer must differ from the submitter" cannot be
    #: checked at all, and a single user could register a controlled-drug
    #: licence and then verify their own evidence.
    #: Nullable because rows predating this field have no recorded submitter --
    #: backfilling a guess would assert a fact nobody established.
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_qualifications",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    #: Why a qualification was rejected or revoked. Immutable once written.
    decision_reason = models.TextField(blank=True, default="")
    #: How the evidence was checked. No regulator is contacted, so this records
    #: MANUAL_INTERNAL_VERIFICATION rather than implying a PPB lookup.
    verification_basis = models.CharField(max_length=64, blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"{self.supplier.supplier_code} - {self.get_qualification_type_display()} ({self.verification_status})"


class SupplierProductAgreement(TimestampedModel):
    """
    Agreement linking a Supplier to an authoritative CommercialSKU.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        TERMINATED = "TERMINATED", "Terminated"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="supplier_agreements")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="product_agreements")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.CASCADE, related_name="supplier_agreements")
    supplier_catalogue_number = models.CharField(max_length=128, blank=True, default="")
    purchase_unit = models.CharField(max_length=64, default="pack")
    agreed_unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="KES")
    minimum_order_quantity = models.PositiveIntegerField(default=1)
    lead_time_days = models.PositiveIntegerField(default=3)
    is_preferred = models.BooleanField(default=False)
    requires_cold_chain = models.BooleanField(default=False)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE, db_index=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "supplier", "sku"], name="unique_tenant_supplier_sku_agreement")
        ]

    def __str__(self):
        return f"{self.supplier.legal_name} - {self.sku.sku_code} @ {self.currency} {self.agreed_unit_price}"


class PurchaseRequisition(TimestampedModel):
    """
    Internal demand request.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        APPROVED = "APPROVED", "Approved"
        PARTIALLY_ORDERED = "PARTIALLY_ORDERED", "Partially Ordered"
        FULLY_ORDERED = "FULLY_ORDERED", "Fully Ordered"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
        CLOSED = "CLOSED", "Closed"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="purchase_requisitions")
    requisition_number = models.CharField(max_length=64, db_index=True)
    requesting_branch = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="requisitions")
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_requisitions")
    requested_delivery_date = models.DateField()
    priority = models.CharField(max_length=32, default="NORMAL")
    justification = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_requisitions"
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "requisition_number"], name="unique_tenant_requisition_number")
        ]

    def __str__(self):
        return f"REQ {self.requisition_number} ({self.status})"


class PurchaseRequisitionLine(TimestampedModel):

    class LineStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        ORDERED = "ORDERED", "Ordered"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="requisition_lines")
    requisition = models.ForeignKey(PurchaseRequisition, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.PROTECT, related_name="requisition_lines")
    requested_quantity = models.PositiveIntegerField()
    approved_quantity = models.PositiveIntegerField(default=0)
    outstanding_quantity = models.PositiveIntegerField(default=0)
    purchase_unit = models.CharField(max_length=64, default="pack")
    status = models.CharField(max_length=32, choices=LineStatus.choices, default=LineStatus.PENDING)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"{self.requisition.requisition_number} - {self.sku.sku_code} ({self.requested_quantity})"


class PurchaseOrder(TimestampedModel):
    """
    Authorized commercial commitment to a supplier.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        SENT = "SENT", "Sent"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED", "Partially Received"
        FULLY_RECEIVED = "FULLY_RECEIVED", "Fully Received"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"
        REJECTED = "REJECTED", "Rejected"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="purchase_orders")
    po_number = models.CharField(max_length=64, db_index=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    originating_requisition = models.ForeignKey(
        PurchaseRequisition, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_orders"
    )
    ordering_branch = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="purchase_orders")
    order_date = models.DateField()
    expected_delivery_date = models.DateField()
    currency = models.CharField(max_length=3, default="KES")
    total_net = models.DecimalField(max_digits=14, decimal_places=2, default=decimal.Decimal("0.00"))
    total_tax = models.DecimalField(max_digits=14, decimal_places=2, default=decimal.Decimal("0.00"))
    total_gross = models.DecimalField(max_digits=14, decimal_places=2, default=decimal.Decimal("0.00"))
    revision_number = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    #: Who raised the order. ProcurementService.create_purchase_order has always
    #: accepted a created_by argument and silently dropped it, so segregation of
    #: duties on approval could not be checked at all -- one person could raise
    #: a purchase order and approve their own commitment.
    #: Nullable because orders predating this field have no recorded creator;
    #: backfilling a guess would assert a fact nobody established.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_purchase_orders",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_pos"
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "po_number"], name="unique_tenant_po_number")
        ]

    def __str__(self):
        return f"PO {self.po_number} ({self.supplier.supplier_code}) - {self.status}"


class PurchaseOrderLine(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="po_lines")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.PROTECT, related_name="po_lines")
    supplier_agreement = models.ForeignKey(
        SupplierProductAgreement, null=True, blank=True, on_delete=models.SET_NULL, related_name="po_lines"
    )
    ordered_quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField(default=0)
    rejected_quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_price = models.DecimalField(max_digits=14, decimal_places=2)
    purchase_unit = models.CharField(max_length=64, default="pack")
    requires_cold_chain = models.BooleanField(default=False)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"PO {self.purchase_order.po_number} - {self.sku.sku_code} ({self.ordered_quantity})"


class PurchaseOrderRevision(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="po_revisions")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    change_reason = models.TextField()
    previous_snapshot = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"PO {self.purchase_order.po_number} Rev {self.revision_number}"


class GoodsReceipt(TimestampedModel):
    """
    Physical arrival of goods.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        RECEIVING = "RECEIVING", "Receiving"
        RECEIVED = "RECEIVED", "Received"
        UNDER_INSPECTION = "UNDER_INSPECTION", "Under Inspection"
        PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED", "Partially Accepted"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="goods_receipts")
    grn_number = models.CharField(max_length=64, db_index=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="goods_receipts")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="goods_receipts")
    receiving_branch = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="goods_receipts")
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_grns")
    delivery_note_number = models.CharField(max_length=128)
    arrival_time = models.DateTimeField()
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    discrepancy_summary = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "grn_number"], name="unique_tenant_grn_number"),
            models.UniqueConstraint(fields=["tenant", "supplier", "delivery_note_number"], name="unique_tenant_supplier_delivery_note")
        ]

    def __str__(self):
        return f"GRN {self.grn_number} (PO {self.purchase_order.po_number})"


class GoodsReceiptLine(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="grn_lines")
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    po_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT, related_name="grn_lines")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.PROTECT, related_name="grn_lines")
    delivered_quantity = models.PositiveIntegerField()
    accepted_quantity = models.PositiveIntegerField(default=0)
    quarantined_quantity = models.PositiveIntegerField(default=0)
    rejected_quantity = models.PositiveIntegerField(default=0)
    discrepancy_reason = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=128, blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="unique_grn_line_idempotency"
            )
        ]

    def __str__(self):
        return f"GRN {self.goods_receipt.grn_number} Line - {self.sku.sku_code} ({self.delivered_quantity})"


class ReceivedBatch(TimestampedModel):
    """
    Batch & expiry capture for received physical stock.
    """

    class QualityStatus(models.TextChoices):
        PENDING_INSPECTION = "PENDING_INSPECTION", "Pending Inspection"
        QUARANTINED = "QUARANTINED", "Quarantined"
        RELEASED = "RELEASED", "Released"
        REJECTED = "REJECTED", "Rejected"
        RETURN_PENDING = "RETURN_PENDING", "Return Pending"
        RETURNED = "RETURNED", "Returned"
        DESTROYED = "DESTROYED", "Destroyed"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="received_batches")
    grn_line = models.ForeignKey(GoodsReceiptLine, on_delete=models.CASCADE, related_name="batches")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.PROTECT, related_name="received_batches")
    manufacturer_batch_number = models.CharField(max_length=128, db_index=True)
    manufacture_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField()
    received_quantity = models.PositiveIntegerField()
    accepted_quantity = models.PositiveIntegerField(default=0)
    quarantined_quantity = models.PositiveIntegerField(default=0)
    rejected_quantity = models.PositiveIntegerField(default=0)
    quality_status = models.CharField(
        max_length=32, choices=QualityStatus.choices, default=QualityStatus.PENDING_INSPECTION, db_index=True
    )
    temperature_excursion = models.BooleanField(default=False)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"Batch {self.manufacturer_batch_number} ({self.sku.sku_code}) Exp: {self.expiry_date}"


class ReceivingInspection(TimestampedModel):

    class Decision(models.TextChoices):
        RELEASE = "RELEASE", "Release to Available Stock"
        QUARANTINE = "QUARANTINE", "Quarantine for Investigation"
        REJECT = "REJECT", "Reject & Return"
        HOLD_FOR_INVESTIGATION = "HOLD_FOR_INVESTIGATION", "Hold for Technical Review"
        DESTROY = "DESTROY", "Condemn & Destroy"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="receiving_inspections")
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="inspections")
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=32, choices=Decision.choices)
    reason = models.TextField()
    inspected_at = models.DateTimeField(auto_now_add=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"Inspection GRN {self.goods_receipt.grn_number} - Decision: {self.decision}"


class SupplierReturn(TimestampedModel):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        REQUESTED = "REQUESTED", "Requested"
        APPROVED = "APPROVED", "Approved"
        READY_FOR_DISPATCH = "READY_FOR_DISPATCH", "Ready for Dispatch"
        DISPATCHED = "DISPATCHED", "Dispatched"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        CREDIT_PENDING = "CREDIT_PENDING", "Credit Pending"
        CLOSED = "CLOSED", "Closed"
        REJECTED = "REJECTED", "Rejected"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="supplier_returns")
    return_number = models.CharField(max_length=64, db_index=True)
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="supplier_returns")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="supplier_returns")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    reason = models.TextField()

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "return_number"], name="unique_tenant_return_number")
        ]

    def __str__(self):
        return f"Return {self.return_number} ({self.status})"


class SupplierReturnLine(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="return_lines")
    supplier_return = models.ForeignKey(SupplierReturn, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.PROTECT)
    batch = models.ForeignKey(ReceivedBatch, null=True, blank=True, on_delete=models.SET_NULL)
    quantity = models.PositiveIntegerField()

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"Return {self.supplier_return.return_number} - {self.sku.sku_code} ({self.quantity})"


class ThreeWayMatch(TimestampedModel):

    class MatchingStatus(models.TextChoices):
        UNMATCHED = "UNMATCHED", "Unmatched"
        MATCHED = "MATCHED", "Matched"
        VARIANCE_FLAGGED = "VARIANCE_FLAGGED", "Variance Flagged"
        ACCEPTED_WITH_VARIANCE = "ACCEPTED_WITH_VARIANCE", "Accepted With Variance"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="three_way_matches")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="three_way_matches")
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="three_way_matches")
    invoice_reference = models.CharField(max_length=128, blank=True, default="")
    matching_status = models.CharField(
        max_length=32, choices=MatchingStatus.choices, default=MatchingStatus.UNMATCHED, db_index=True
    )
    quantity_variance = models.IntegerField(default=0)
    price_variance = models.DecimalField(max_digits=12, decimal_places=2, default=decimal.Decimal("0.00"))

    objects = StrictTenantManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"3-Way Match PO {self.purchase_order.po_number} / GRN {self.goods_receipt.grn_number} - {self.matching_status}"


# ==============================================================================
# EXTENDED PROCUREMENT & SUPPLIER GOVERNANCE MODELS
# ==============================================================================

class SupplierSite(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="sites")
    site_code = models.CharField(max_length=64)
    site_name = models.CharField(max_length=255)
    address = models.TextField(blank=True, default="")
    is_primary = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class RequestForQuotation(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    rfq_number = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=255)
    issue_date = models.DateField(auto_now_add=True)
    closing_date = models.DateField()
    status = models.CharField(max_length=32, default="OPEN")

    objects = StrictTenantManager()
    all_objects = models.Manager()


class RFQLine(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    rfq = models.ForeignKey(RequestForQuotation, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.PROTECT, related_name="+")
    requested_quantity = models.PositiveIntegerField()

    objects = StrictTenantManager()
    all_objects = models.Manager()


class SupplierQuotation(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    rfq = models.ForeignKey(RequestForQuotation, on_delete=models.CASCADE, related_name="quotations")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="+")
    quotation_reference = models.CharField(max_length=128)
    total_quoted_cost = models.DecimalField(max_digits=15, decimal_places=2)
    valid_until = models.DateField()
    status = models.CharField(max_length=32, default="SUBMITTED")

    objects = StrictTenantManager()
    all_objects = models.Manager()


class SupplierQuotationLine(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    quotation = models.ForeignKey(SupplierQuotation, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.PROTECT, related_name="+")
    quoted_quantity = models.PositiveIntegerField()
    quoted_unit_cost = models.DecimalField(max_digits=15, decimal_places=2)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class QuotationAward(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    rfq = models.OneToOneField(RequestForQuotation, on_delete=models.CASCADE, related_name="award")
    winning_quotation = models.ForeignKey(SupplierQuotation, on_delete=models.CASCADE, related_name="+")
    awarded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    awarded_at = models.DateTimeField(auto_now_add=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()


class ReceivingSession(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    session_number = models.CharField(max_length=64, db_index=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="receiving_sessions")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="+")
    branch = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="+")
    delivery_note_number = models.CharField(max_length=128)
    status = models.CharField(max_length=32, default="ACTIVE")
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    objects = StrictTenantManager()
    all_objects = models.Manager()


class ReceivingScan(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    session = models.ForeignKey(ReceivingSession, on_delete=models.CASCADE, related_name="scans")
    sku = models.ForeignKey(CommercialSKU, on_delete=models.PROTECT, related_name="+")
    scanned_barcode = models.CharField(max_length=128)
    batch_number = models.CharField(max_length=128)
    expiry_date = models.DateField()
    scanned_quantity = models.PositiveIntegerField()

    objects = StrictTenantManager()
    all_objects = models.Manager()


class QualityDecision(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="quality_decisions")
    batch = models.ForeignKey(ReceivedBatch, on_delete=models.CASCADE, related_name="+")
    decision = models.CharField(max_length=32, default="RELEASED")
    decision_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decision_notes = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

class ProcurementPolicy(TimestampedModel):
    """Per-tenant procurement rules that are policy rather than law.

    Some procurement constraints are not negotiable -- a suspended supplier
    cannot be awarded to, a return cannot exceed what was rejected. Those stay
    in the services.

    Awarding above the lowest quotation is different. It is legitimate for
    quality, lead time, cold chain or capacity, and how strictly it is policed
    varies by organisation. That belongs here, where a pharmacy group can set it,
    rather than being fixed in code for everybody.
    """

    class AwardAboveLowest(models.TextChoices):
        #: Permitted, with a stated reason recorded on the award. The default,
        #: and what the service enforced before this was configurable.
        REQUIRE_REASON = "REQUIRE_REASON", "Require a stated reason"
        #: Refused outright. The lowest compliant quotation wins.
        BLOCK = "BLOCK", "Award the lowest quotation only"
        #: Permitted with no reason. For groups whose controls sit elsewhere.
        ALLOW = "ALLOW", "Allow without explanation"

    tenant = models.OneToOneField(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="procurement_policy"
    )
    award_above_lowest = models.CharField(
        max_length=20,
        choices=AwardAboveLowest.choices,
        default=AwardAboveLowest.REQUIRE_REASON,
    )
    #: Below this margin over the lowest quotation, no reason is asked for.
    #:
    #: Awarding 0.4% above the lowest quote is rounding; 40% is a decision.
    #: Treating both the same trains buyers to type "cheapest declined" into
    #: every award, which is how a control becomes a formality.
    award_variance_tolerance_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        verbose_name_plural = "procurement policies"

    def __str__(self) -> str:
        return f"Procurement policy for {self.tenant}"

    @classmethod
    def for_tenant(cls, tenant):
        """The tenant's policy, or the default one.

        Returns an unsaved instance when none is configured rather than creating
        a row on read: a policy nobody set should not start existing because
        somebody looked at a tender.
        """
        existing = cls.all_objects.filter(tenant=tenant).first()
        return existing if existing is not None else cls(tenant=tenant)
