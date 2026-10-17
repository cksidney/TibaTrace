"""Taxation and KRA eTIMS VSCU domain models."""
from __future__ import annotations

from decimal import Decimal

from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel

MONEY = {"max_digits": 15, "decimal_places": 2}


class TenantEtimsProfile(TenantConsistencyMixin, TimestampedModel):
    """Per-tenant KRA eTIMS VSCU configuration.

    Stores tenant-specific eTIMS details (PIN, Branch ID, Device Serial,
    CM Key, SDC ID, and sequential counters). Each tenant configures their own
    credentials during onboarding/setup via the HQ Web interface or API.
    """

    class Environment(models.TextChoices):
        SANDBOX = "SANDBOX", "Sandbox / Testing"
        PRODUCTION = "PRODUCTION", "Production"

    tenant_relation_fields = ()

    tenant = models.OneToOneField(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="etims_profile",
    )
    is_enabled = models.BooleanField(
        default=False,
        help_text="Enable live/sandbox eTIMS fiscalization for this tenant.",
    )
    environment = models.CharField(
        max_length=20,
        choices=Environment.choices,
        default=Environment.SANDBOX,
        help_text="Target KRA eTIMS environment.",
    )
    tin = models.CharField(
        max_length=20,
        blank=True,
        help_text="Taxpayer Identification Number (KRA PIN, e.g. P051234567Z).",
    )
    bhf_id = models.CharField(
        max_length=10,
        default="00",
        help_text="Branch identifier registered with KRA (e.g. '00' for main branch).",
    )
    dvc_srl_no = models.CharField(
        max_length=100,
        blank=True,
        help_text="Virtual Sales Control Unit (VSCU) device serial number assigned by KRA.",
    )
    cm_key = models.CharField(
        max_length=255,
        blank=True,
        help_text="Communication AES encryption key returned from KRA VSCU initialization.",
    )
    base_url = models.URLField(
        max_length=255,
        default="https://etims-sbx.kra.go.ke",
        help_text="Base URL of the KRA eTIMS VSCU API.",
    )
    taxpayer_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Registered taxpayer entity name returned by KRA.",
    )
    branch_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Registered branch name returned by KRA.",
    )
    sdc_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Sales Control Unit ID (returned upon device initialization).",
    )
    mrc_no = models.CharField(
        max_length=100,
        blank=True,
        help_text="Machine Registration Code.",
    )
    last_invoice_number = models.PositiveIntegerField(
        default=0,
        help_text="Last issued fiscal invoice sequence number.",
    )
    last_credit_note_number = models.PositiveIntegerField(
        default=0,
        help_text="Last issued credit note sequence number.",
    )
    auto_fiscalize_pos_sales = models.BooleanField(
        default=True,
        help_text="Automatically transmit retail POS sales to eTIMS upon settlement.",
    )
    is_initialized = models.BooleanField(
        default=False,
        help_text="Indicates whether the VSCU device handshake (selectInitInfo) has completed.",
    )
    last_sync_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of last successful contact with KRA VSCU API.",
    )
    notes = models.TextField(blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "is_enabled"], name="ix_etims_profile_tenant_en"),
        ]

    def __str__(self) -> str:
        return f"TenantEtimsProfile(tenant={self.tenant_id}, tin={self.tin}, env={self.environment})"

    @property
    def is_configured(self) -> bool:
        """Returns True if the minimum required credentials have been configured."""
        return bool(self.tin and self.bhf_id and self.dvc_srl_no)


class FiscalReceipt(TenantConsistencyMixin, TimestampedModel):
    """Fiscal record of a sale or refund transmitted or queued for KRA eTIMS."""

    class ReceiptType(models.TextChoices):
        SALE = "SALE", "Sale Invoice"
        CREDIT_NOTE = "CREDIT_NOTE", "Credit Note / Refund"

    class SubmissionStatus(models.TextChoices):
        PENDING = "PENDING", "Pending Transmission"
        SUBMITTED = "SUBMITTED", "Submitted / Fiscalized"
        FAILED = "FAILED", "Transmission Failed / Retry Queued"
        OFFLINE_GENERATED = "OFFLINE_GENERATED", "Locally Fiscalized (Pending Sync)"

    tenant_relation_fields = ("pos_transaction", "retail_cash_receipt", "retail_cash_refund")

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="fiscal_receipts",
    )
    pos_transaction = models.ForeignKey(
        "pos_transactions.PosTransaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fiscal_receipts",
    )
    retail_cash_receipt = models.ForeignKey(
        "pos_transactions.RetailCashReceipt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fiscal_receipts",
    )
    retail_cash_refund = models.ForeignKey(
        "pos_transactions.RetailCashRefund",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fiscal_receipts",
    )
    receipt_type = models.CharField(
        max_length=20,
        choices=ReceiptType.choices,
        default=ReceiptType.SALE,
    )
    invoice_number = models.PositiveIntegerField(
        help_text="Sequential invoice number (invcNo) issued for KRA eTIMS.",
    )
    original_invoice_number = models.PositiveIntegerField(
        default=0,
        help_text="Original invoice number (orgInvcNo) when issuing a credit note/refund.",
    )
    sales_type_code = models.CharField(
        max_length=2,
        default="N",
        help_text="KRA salesTyCd: N (Normal), C (Copy), T (Training), P (Proforma).",
    )
    receipt_type_code = models.CharField(
        max_length=2,
        default="S",
        help_text="KRA rcptTyCd: S (Sale), R (Refund / Credit Note).",
    )
    payment_type_code = models.CharField(
        max_length=2,
        default="01",
        help_text="KRA pmtTyCd: 01 (Cash), 02 (Credit), 05 (Card), 06 (Mobile Money).",
    )
    customer_pin = models.CharField(max_length=20, blank=True)
    customer_name = models.CharField(max_length=255, blank=True)
    customer_mobile = models.CharField(max_length=20, blank=True)

    # KRA Tax Breakdown Buckets
    taxable_amount_a = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Taxable A (Standard 16%)")
    tax_amount_a = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Tax A (16%)")
    taxable_amount_b = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Taxable B (Zero Rated 0%)")
    tax_amount_b = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Tax B (0%)")
    taxable_amount_c = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Taxable C (8%)")
    tax_amount_c = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Tax C (8%)")
    taxable_amount_d = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Taxable D (Non-VAT)")
    tax_amount_d = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Tax D")
    taxable_amount_e = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Taxable E (Exempt - Medicines)")
    tax_amount_e = models.DecimalField(default=Decimal("0.00"), **MONEY, help_text="Tax E (Exempt 0%)")
    total_taxable_amount = models.DecimalField(default=Decimal("0.00"), **MONEY)
    total_tax_amount = models.DecimalField(default=Decimal("0.00"), **MONEY)
    total_amount = models.DecimalField(default=Decimal("0.00"), **MONEY)
    currency = models.CharField(max_length=3, default="KES")

    # KRA Verification & QR
    internal_data = models.CharField(max_length=128, blank=True, help_text="KRA internal data string (intrlData).")
    receipt_signature = models.CharField(max_length=128, blank=True, help_text="KRA receipt signature (rcptSign).")
    qr_code_url = models.TextField(blank=True, help_text="Official KRA verification URL.")
    qr_code_image_data = models.TextField(blank=True, help_text="SVG QR code data for receipt rendering.")

    # Status & Durability
    submission_status = models.CharField(
        max_length=30,
        choices=SubmissionStatus.choices,
        default=SubmissionStatus.PENDING,
        db_index=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    raw_request_payload = models.JSONField(default=dict, blank=True)
    raw_response_payload = models.JSONField(default=dict, blank=True)
    items_snapshot = models.JSONField(default=list, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "receipt_type", "invoice_number"],
                name="uq_fiscal_receipt_tenant_type_invoice",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "submission_status", "next_retry_at"], name="ix_fiscal_rcpt_retry"),
            models.Index(fields=["tenant", "invoice_number"], name="ix_fiscal_rcpt_invc"),
        ]

    def __str__(self) -> str:
        return f"FiscalReceipt({self.tenant_id}, #{self.invoice_number}, {self.receipt_type}, {self.submission_status})"


class FiscalSubmissionLog(TenantConsistencyMixin, TimestampedModel):
    """Immutable log of communication attempts with KRA eTIMS VSCU API."""

    tenant_relation_fields = ("fiscal_receipt",)

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="fiscal_submission_logs",
    )
    fiscal_receipt = models.ForeignKey(
        FiscalReceipt,
        on_delete=models.CASCADE,
        related_name="submission_logs",
    )
    endpoint = models.CharField(max_length=120)
    status_code = models.IntegerField(null=True, blank=True)
    success = models.BooleanField()
    response_time_ms = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    response_payload = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="ix_fiscal_log_tenant_date"),
        ]

    def __str__(self) -> str:
        return f"FiscalSubmissionLog(receipt={self.fiscal_receipt_id}, endpoint={self.endpoint}, success={self.success})"
