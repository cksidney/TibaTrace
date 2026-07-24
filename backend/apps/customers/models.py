from django.conf import settings
from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class Customer(TenantConsistencyMixin, TimestampedModel):
    class CustomerType(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        PHARMACY = "PHARMACY", "Pharmacy"
        HOSPITAL = "HOSPITAL", "Hospital"
        CLINIC = "CLINIC", "Clinic"
        RETAIL = "RETAIL", "Retail"
        WHOLESALE = "WHOLESALE", "Wholesale"
        WHOLESALER = "WHOLESALER", "Wholesaler"
        DISTRIBUTOR = "DISTRIBUTOR", "Distributor"
        GOVERNMENT = "GOVERNMENT", "Government"
        NGO = "NGO", "NGO"
        INSURER = "INSURER", "Insurer"
        CORPORATE = "CORPORATE", "Corporate"
        INTERNAL = "INTERNAL", "Internal"

    class Status(models.TextChoices):
        PROSPECTIVE = "PROSPECTIVE", "Prospective"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        APPROVED = "APPROVED", "Approved"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        BLOCKED = "BLOCKED", "Blocked"
        ARCHIVED = "ARCHIVED", "Archived"

    class RiskClassification(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class CreditStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CREDIT_HOLD = "CREDIT_HOLD", "Credit Hold"
        PAYMENT_REQUIRED = "PAYMENT_REQUIRED", "Payment Required"
        MANUAL_REVIEW = "MANUAL_REVIEW", "Manual Review"
        BLOCKED = "BLOCKED", "Blocked"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="customers")
    customer_number = models.CharField(max_length=64, db_index=True)
    legal_name = models.CharField(max_length=255)
    trading_name = models.CharField(max_length=255, blank=True, default="")
    customer_type = models.CharField(max_length=64, choices=CustomerType.choices)
    registration_number = models.CharField(max_length=128, blank=True, default="")
    tax_number = models.CharField(max_length=128, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=64, blank=True, default="")

    billing_address_line1 = models.CharField(max_length=255, blank=True, default="")
    billing_address_line2 = models.CharField(max_length=255, blank=True, default="")
    billing_city = models.CharField(max_length=128, blank=True, default="")
    billing_county = models.CharField(max_length=128, blank=True, default="")
    billing_postal_code = models.CharField(max_length=32, blank=True, default="")
    billing_country = models.CharField(max_length=100, default="Kenya")

    status = models.CharField(max_length=64, choices=Status.choices, default=Status.PROSPECTIVE, db_index=True)
    risk_classification = models.CharField(
        max_length=64, choices=RiskClassification.choices, default=RiskClassification.MEDIUM
    )
    credit_status = models.CharField(max_length=64, choices=CreditStatus.choices, default=CreditStatus.ACTIVE)
    default_currency = models.CharField(max_length=3, default="KES")
    payment_terms = models.CharField(max_length=128, default="NET30")
    ordering_restrictions = models.TextField(blank=True, default="")
    controlled_medicine_eligible = models.BooleanField(default=False)
    cold_chain_capable = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "customer_number"], name="uq_customer_number")]
        indexes = [models.Index(fields=["tenant", "status"], name="ix_customer_tenant_status")]

    def __str__(self):
        return f"{self.legal_name} [{self.customer_number}]"


class CustomerDeliveryAddress(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("customer",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="delivery_addresses")
    address_code = models.CharField(max_length=64)
    recipient_name = models.CharField(max_length=255)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=128)
    county = models.CharField(max_length=128, blank=True, default="")
    postal_code = models.CharField(max_length=32, blank=True, default="")
    country = models.CharField(max_length=100, default="Kenya")
    phone = models.CharField(max_length=64, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    delivery_instructions = models.TextField(blank=True, default="")
    route_zone = models.CharField(max_length=64, blank=True, default="")
    cold_chain_capable = models.BooleanField(default=False)
    controlled_medicine_capable = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["customer", "address_code"], name="uq_customer_address_code")]

    def __str__(self):
        return f"{self.recipient_name} ({self.address_code})"


class CustomerCommercialProfile(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("customer", "default_branch", "default_delivery_address")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    customer = models.OneToOneField(Customer, on_delete=models.PROTECT, related_name="commercial_profile")
    price_list = models.ForeignKey(
        "sales.PriceList", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    discount_policy = models.CharField(max_length=128, blank=True, default="")
    tax_treatment = models.CharField(max_length=64, default="STANDARD")
    payment_terms = models.CharField(max_length=128, blank=True, default="")
    credit_limit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    order_limit = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    minimum_order_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    controlled_product_authorized = models.BooleanField(default=False)
    cold_chain_delivery_capable = models.BooleanField(default=False)
    required_purchase_order_reference = models.BooleanField(default=False)
    default_branch = models.ForeignKey(
        "organizations.Location", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    default_delivery_address = models.ForeignKey(
        CustomerDeliveryAddress, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    allowed_sku_categories = models.JSONField(default=list, blank=True)
    blocked_skus = models.ManyToManyField("medicines.CommercialSKU", blank=True, related_name="+")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "customer"], name="uq_customer_commercial_profile")]
