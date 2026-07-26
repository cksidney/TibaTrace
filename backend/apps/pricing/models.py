"""Versioned price books, scope assignments and applied-price snapshots.

Three properties the schema enforces rather than documents.

**A published version is immutable.** Changing a price creates a new version;
it never edits a live one. Editing in place silently rewrites what every
historical receipt claims to have charged, and there is then no way to answer
what a customer was actually asked to pay last Tuesday.

**Branch pricing is sparse.** A branch inherits its tenant's price book and
stores only the items it charges differently for. Copying the full list per
branch means a tenant with four hundred branches carries four hundred copies of
every price, and a single tenant-wide change becomes four hundred writes that
can half-fail.

**Every sold line keeps its own price snapshot.** The price that was charged is
recorded on the transaction, not looked up again later. A receipt reprinted
after a price rise must show what the customer paid, not what the item costs
today.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel

MONEY = {"max_digits": 15, "decimal_places": 2}
QUANTITY = {"max_digits": 15, "decimal_places": 4}
ZERO = Decimal("0.00")


class PriceBook(TenantConsistencyMixin, TimestampedModel):
    """A commercial pricing context: a set of prices with a purpose."""

    class PriceType(models.TextChoices):
        BASE = "BASE", "Base"
        RETAIL = "RETAIL", "Retail"
        WHOLESALE = "WHOLESALE", "Wholesale"
        BRANCH_RETAIL = "BRANCH_RETAIL", "Branch retail"
        BRANCH_WHOLESALE = "BRANCH_WHOLESALE", "Branch wholesale"
        CUSTOMER_CONTRACT = "CUSTOMER_CONTRACT", "Customer contract"
        INSURANCE_TARIFF = "INSURANCE_TARIFF", "Insurance tariff"
        STAFF = "STAFF", "Staff"
        PROMOTIONAL = "PROMOTIONAL", "Promotional"

    class ScopeType(models.TextChoices):
        TENANT = "TENANT", "Tenant"
        REGION = "REGION", "Region"
        BRANCH_GROUP = "BRANCH_GROUP", "Branch group"
        BRANCH = "BRANCH", "Branch"
        CUSTOMER_SEGMENT = "CUSTOMER_SEGMENT", "Customer segment"
        CUSTOMER = "CUSTOMER", "Customer"
        INSURER = "INSURER", "Insurer"
        INSURANCE_PLAN = "INSURANCE_PLAN", "Insurance plan"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="price_books")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    currency = models.CharField(max_length=3, default="KES")
    price_type = models.CharField(max_length=32, choices=PriceType.choices, default=PriceType.RETAIL)
    scope_type = models.CharField(max_length=32, choices=ScopeType.choices, default=ScopeType.TENANT)
    #: Breaks ties between books of the same scope. Resolution refuses on a true
    #: tie, so this is what stops two branch books ever reaching that point.
    priority = models.IntegerField(default=0)
    tax_inclusive = models.BooleanField(default=True)
    rounding_policy = models.CharField(max_length=32, default="HALF_UP")
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uq_price_book_tenant_code")
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.get_price_type_display()})"


class PriceBookVersion(TenantConsistencyMixin, TimestampedModel):
    """One dated, approvable revision of a price book.

    Immutable once published. `save()` refuses to alter a published row, and
    corrections go through a new version -- a published price is what somebody
    was charged, and rewriting it destroys the only record of that.
    """

    tenant_relation_fields = ("price_book",)

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        APPROVED = "APPROVED", "Approved"
        SCHEDULED = "SCHEDULED", "Scheduled"
        ACTIVE = "ACTIVE", "Active"
        SUPERSEDED = "SUPERSEDED", "Superseded"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    #: States in which the version's prices are fixed and may have been charged.
    PUBLISHED_STATES = frozenset({"ACTIVE", "SCHEDULED", "SUPERSEDED", "EXPIRED"})

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    price_book = models.ForeignKey(PriceBook, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["price_book", "version_number"], name="uq_price_book_version_number"
            )
        ]
        ordering = ["price_book_id", "-version_number"]

    def __str__(self) -> str:
        return f"{self.price_book_id} v{self.version_number} [{self.status}]"

    @property
    def is_published(self) -> bool:
        return self.status in self.PUBLISHED_STATES

    def applies_on(self, service_date) -> bool:
        if self.effective_from and service_date < self.effective_from:
            return False
        if self.effective_to and service_date > self.effective_to:
            return False
        return True

    def save(self, *args, **kwargs):
        # `_state.adding`, not `if self.pk`. These models use UUID primary keys,
        # which are populated before the insert, so `self.pk` is truthy on
        # creation too and a pk test would refuse every new row.
        if not self._state.adding:
            existing = (
                PriceBookVersion.all_objects.filter(pk=self.pk, tenant_id=self.tenant_id)
                .values("status", "effective_from", "effective_to", "version_number")
                .first()
            )
            if existing and existing["status"] in self.PUBLISHED_STATES:
                # Status may still advance -- ACTIVE to SUPERSEDED is how a
                # version retires. What may not change is what it says.
                changed_dates = (
                    self.effective_from != existing["effective_from"]
                    or self.effective_to != existing["effective_to"]
                )
                if changed_dates or self.version_number != existing["version_number"]:
                    raise ValidationError(
                        "A published price-book version cannot be re-dated or "
                        "renumbered. Publish a new version instead."
                    )
        return super().save(*args, **kwargs)


class PriceBookEntry(TenantConsistencyMixin, TimestampedModel):
    """One item's price within a version.

    Entries belong to a version, not to a book, so a price change never mutates
    a row somebody has already been charged against.
    """

    tenant_relation_fields = ("version", "sku")

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    version = models.ForeignKey(PriceBookVersion, on_delete=models.CASCADE, related_name="entries")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    unit_price = models.DecimalField(**MONEY)
    #: Quantity band. A wholesale price does not apply to a single pack.
    minimum_quantity = models.DecimalField(default=Decimal("1"), **QUANTITY)
    maximum_quantity = models.DecimalField(null=True, blank=True, **QUANTITY)
    #: Floor below which even an authorised override may not go without
    #: escalation. Held here because it moves with the price, not with the item.
    minimum_allowed_price = models.DecimalField(null=True, blank=True, **MONEY)
    tax_inclusive = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "sku", "minimum_quantity"],
                name="uq_price_entry_version_sku_band",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="chk_price_entry_nonneg"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding and self.version_id and self.version.is_published:
            raise ValidationError(
                "An entry in a published price-book version cannot be edited. "
                "Publish a new version instead."
            )
        return super().save(*args, **kwargs)


class PriceAssignment(TenantConsistencyMixin, TimestampedModel):
    """Which price book applies to which scope.

    This is what keeps branch pricing sparse. A branch does not hold a copy of
    the tenant list; it holds an assignment to it, plus an assignment to its own
    override book if it has one.
    """

    tenant_relation_fields = ("price_book",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="price_assignments")
    price_book = models.ForeignKey(PriceBook, on_delete=models.CASCADE, related_name="assignments")
    scope_type = models.CharField(max_length=32, choices=PriceBook.ScopeType.choices)

    branch = models.ForeignKey(
        "organizations.Location", on_delete=models.CASCADE, null=True, blank=True, related_name="price_assignments"
    )
    branch_group = models.CharField(max_length=64, blank=True, default="")
    region = models.CharField(max_length=64, blank=True, default="")
    customer_segment = models.CharField(max_length=64, blank=True, default="")
    customer_id = models.CharField(max_length=64, blank=True, default="")
    insurer_id = models.CharField(max_length=64, blank=True, default="")
    insurance_plan_id = models.CharField(max_length=64, blank=True, default="")

    priority = models.IntegerField(default=0)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "scope_type", "is_active"]),
            models.Index(fields=["tenant", "branch"]),
        ]

    def applies_on(self, service_date) -> bool:
        if not self.is_active:
            return False
        if self.valid_from and service_date < self.valid_from:
            return False
        if self.valid_to and service_date > self.valid_to:
            return False
        return True


class ManualPriceOverride(TenantConsistencyMixin, TimestampedModel):
    """A price typed by a person, for one line of one transaction.

    Scoped to a transaction deliberately. An override is a decision about a
    particular sale -- a damaged box, a goodwill gesture, a price-match -- and
    letting it touch the master price turns one cashier's judgement into
    everybody's price.
    """

    tenant_relation_fields = ("sku",)

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        APPLIED = "APPLIED", "Applied"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="price_overrides")
    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    #: The transaction this override is confined to.
    transaction_reference = models.CharField(max_length=120)

    resolved_price = models.DecimalField(**MONEY)
    override_price = models.DecimalField(**MONEY)
    reason_code = models.CharField(max_length=64)
    reason = models.TextField(blank=True, default="")

    requested_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    expires_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "transaction_reference"])]

    @property
    def difference(self) -> Decimal:
        return Decimal(str(self.override_price)) - Decimal(str(self.resolved_price))

    @property
    def is_usable(self) -> bool:
        if self.status != self.Status.APPROVED:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True


class AppliedPriceSnapshot(TenantConsistencyMixin, TimestampedModel):
    """What a transaction line was actually charged, and why.

    Written once, never updated. A receipt reprinted after a price rise must
    show what the customer paid; re-resolving it against current prices would
    quietly restate history, and the customer holds the paper copy.
    """

    tenant_relation_fields = ("sku",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="applied_prices")
    #: Whatever the line is -- sale line, dispensing line, claim line. Kept as a
    #: reference rather than a foreign key so one snapshot shape serves all of
    #: them without the pricing app depending on every consumer.
    line_reference = models.CharField(max_length=120)
    line_type = models.CharField(max_length=40, default="SALE")

    sku = models.ForeignKey("medicines.CommercialSKU", on_delete=models.PROTECT, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(**QUANTITY)
    currency = models.CharField(max_length=3, default="KES")

    unit_price = models.DecimalField(**MONEY)
    line_total = models.DecimalField(**MONEY)
    discount_amount = models.DecimalField(default=ZERO, **MONEY)
    tax_amount = models.DecimalField(default=ZERO, **MONEY)

    source = models.CharField(max_length=40)
    source_reference = models.CharField(max_length=120, blank=True, default="")
    price_book_version = models.ForeignKey(
        PriceBookVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    manual_override = models.ForeignKey(
        ManualPriceOverride, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    #: The full ranked trace, so the charge stays explicable after the fact.
    resolution_trace = models.JSONField(default=list, blank=True)
    context_hash = models.CharField(max_length=64, blank=True, default="")
    resolved_at = models.DateTimeField(default=timezone.now)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "line_reference", "line_type"],
                name="uq_applied_price_per_line",
            )
        ]
        indexes = [models.Index(fields=["tenant", "sku", "resolved_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            # Append-only. The charge happened; it does not get revised.
            raise ValidationError(
                "An applied price snapshot cannot be modified. It records what a "
                "customer was charged."
            )
        return super().save(*args, **kwargs)
