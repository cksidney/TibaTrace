"""Register sessions, operator shifts and the cash ledger beneath them.

Four periods that are routinely conflated and must not be:

* **Business day** — the accounting date transactions belong to. Not midnight:
  a till open at 01:00 is usually still on yesterday's day.
* **Register session** — the financially controlled period from opening cash to
  final Z closure. Exactly one may be active per register.
* **Operator shift** — who is accountable. Several may run inside one register
  session as staff hand over.
* **User session** — authentication, handled in identity.pos_authentication.

Money is `Decimal` throughout, never float. A shift that reconciles to within a
cent on paper and drifts in binary is worse than one that is visibly wrong,
because nobody investigates it.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel

MONEY = {"max_digits": 14, "decimal_places": 2}
ZERO = Decimal("0.00")


class BusinessDay(TenantConsistencyMixin, TimestampedModel):
    """The accounting date a register session belongs to."""

    STATES = [
        ("PLANNED", "Planned"),
        ("OPEN", "Open"),
        ("CLOSING", "Closing"),
        ("CLOSED", "Closed"),
        ("REOPENED_BY_EXCEPTION", "Reopened by exception"),
    ]

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="business_days")
    location = models.ForeignKey(
        "organizations.Location", on_delete=models.PROTECT, related_name="business_days"
    )
    business_date = models.DateField()
    state = models.CharField(max_length=30, choices=STATES, default="OPEN")
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reopen_reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "location", "business_date"], name="uq_business_day_tenant_loc_date"
            )
        ]
        ordering = ["-business_date"]

    def __str__(self) -> str:
        return f"{self.business_date} [{self.state}]"

    @property
    def accepts_transactions(self) -> bool:
        return self.state in {"OPEN", "REOPENED_BY_EXCEPTION"}


class PosRegister(TenantConsistencyMixin, TimestampedModel):
    """A physical till."""

    STATES = [
        ("UNCONFIGURED", "Unconfigured"),
        ("AVAILABLE", "Available"),
        ("OPEN", "Open"),
        ("LOCKED", "Locked"),
        ("CLOSING", "Closing"),
        ("CLOSED", "Closed"),
        ("OFFLINE", "Offline"),
        ("SUSPENDED", "Suspended"),
        ("OUT_OF_SERVICE", "Out of service"),
    ]

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="pos_registers")
    location = models.ForeignKey(
        "organizations.Location", on_delete=models.PROTECT, related_name="pos_registers"
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    device_id = models.CharField(max_length=120, blank=True, default="")
    printer_config = models.JSONField(default=dict, blank=True)
    currency = models.CharField(max_length=3, default="KES")
    state = models.CharField(max_length=20, choices=STATES, default="UNCONFIGURED")
    #: The float the drawer is expected to start each session with.
    expected_float = models.DecimalField(default=ZERO, **MONEY)
    last_synchronised_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uq_pos_register_tenant_code")
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"

    @property
    def accepts_opening(self) -> bool:
        return self.state in {"AVAILABLE", "CLOSED"}


class RegisterSession(TenantConsistencyMixin, TimestampedModel):
    """The financially controlled period between opening and Z closure.

    The partial unique index below is the invariant that matters: at most one
    session per register may be open at a time. Enforced in the database rather
    than in a service, because two concurrent openings would otherwise each see
    an empty result and both proceed.
    """

    tenant_relation_fields = ("register", "business_day")

    STATES = [
        ("OPEN", "Open"),
        ("CLOSING", "Closing"),
        ("CLOSED", "Closed"),
    ]

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="register_sessions")
    register = models.ForeignKey(PosRegister, on_delete=models.PROTECT, related_name="sessions")
    business_day = models.ForeignKey(
        BusinessDay, on_delete=models.PROTECT, related_name="register_sessions"
    )
    state = models.CharField(max_length=20, choices=STATES, default="OPEN")
    opened_at = models.DateTimeField(default=timezone.now)
    opened_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    #: Set when this session was closed by someone other than its operator.
    forced_closure = models.BooleanField(default=False)
    forced_closure_reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["register"],
                condition=models.Q(state__in=["OPEN", "CLOSING"]),
                name="uq_register_one_active_session",
            )
        ]
        ordering = ["-opened_at"]

    def __str__(self) -> str:
        return f"Session {self.pk} on {self.register_id} [{self.state}]"

    @property
    def is_open(self) -> bool:
        return self.state == "OPEN"


class OperatorShift(TenantConsistencyMixin, TimestampedModel):
    """Who is accountable for till activity, and for which stretch of it."""

    tenant_relation_fields = ("register_session",)

    STATES = [
        ("OPEN", "Open"),
        ("HANDOVER_REQUESTED", "Handover requested"),
        ("CLOSED", "Closed"),
        ("FORCE_CLOSED", "Force closed"),
    ]

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="operator_shifts")
    register_session = models.ForeignKey(
        RegisterSession, on_delete=models.PROTECT, related_name="operator_shifts"
    )
    operator = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="operator_shifts")
    state = models.CharField(max_length=25, choices=STATES, default="OPEN")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    #: Who took over, when this shift ended in a handover.
    handed_over_to = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    closed_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    close_reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["register_session"],
                condition=models.Q(state__in=["OPEN", "HANDOVER_REQUESTED"]),
                name="uq_session_one_active_shift",
            )
        ]
        ordering = ["-started_at"]

    @property
    def is_open(self) -> bool:
        return self.state in {"OPEN", "HANDOVER_REQUESTED"}


class CashDeclaration(TenantConsistencyMixin, TimestampedModel):
    """A counted cash position, at opening or closing.

    Immutable once confirmed. A recount creates another declaration rather than
    editing this one, so an operator cannot quietly revise a count after seeing
    the expected figure -- which is the whole point of a blind count.
    """

    tenant_relation_fields = ("register_session",)

    KINDS = [("OPENING", "Opening"), ("CLOSING", "Closing")]

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="cash_declarations")
    register_session = models.ForeignKey(
        RegisterSession, on_delete=models.PROTECT, related_name="cash_declarations"
    )
    operator_shift = models.ForeignKey(
        OperatorShift, on_delete=models.PROTECT, null=True, blank=True, related_name="cash_declarations"
    )
    kind = models.CharField(max_length=10, choices=KINDS)
    declared_amount = models.DecimalField(**MONEY)
    #: Populated when the count was entered denomination by denomination.
    denominations = models.JSONField(default=dict, blank=True)
    currency = models.CharField(max_length=3, default="KES")
    declared_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    supervisor = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    #: Ordinal of this count within its kind. A recount is 2, 3, ...
    attempt = models.PositiveIntegerField(default=1)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["register_session_id", "kind", "attempt"]

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None

    def denomination_total(self) -> Decimal:
        """Sum the denomination breakdown, if one was captured."""
        total = ZERO
        for face_value, quantity in (self.denominations or {}).items():
            total += Decimal(str(face_value)) * Decimal(str(quantity))
        return total.quantize(Decimal("0.01"))

    def save(self, *args, **kwargs):
        if self.pk and self.is_confirmed:
            # Scoped by tenant as well as pk: an unscoped lookup on all_objects
            # is how a cross-tenant read gets introduced by accident, and the
            # repository audit rejects the pattern regardless of the pk being a
            # UUID we just came from.
            existing = (
                CashDeclaration.all_objects.filter(pk=self.pk, tenant_id=self.tenant_id)
                .values("confirmed_at")
                .first()
            )
            if existing and existing["confirmed_at"] is not None:
                # Corrections go through a new declaration, so the original
                # count remains visible next to the revised one.
                allowed = set(kwargs.get("update_fields") or [])
                if not allowed <= {"updated_at"}:
                    raise ValidationError(
                        "A confirmed cash declaration cannot be edited. Record a recount instead."
                    )
        return super().save(*args, **kwargs)


class CashMovement(TenantConsistencyMixin, TimestampedModel):
    """Cash entering or leaving the drawer other than through a sale.

    Direction is explicit rather than implied by sign, so a cash-out can never
    be recorded as a negative sale and disappear from the sales figures while
    still emptying the drawer.
    """

    tenant_relation_fields = ("register_session",)

    KINDS = [
        ("CASH_IN", "Cash in"),
        ("CASH_OUT", "Cash out"),
        ("FLOAT_TOP_UP", "Float top-up"),
        ("SAFE_DROP", "Safe drop"),
        ("PETTY_CASH", "Petty cash"),
        ("BANKING", "Banking"),
        ("CORRECTION", "Correction"),
        ("OTHER_AUTHORISED_MOVEMENT", "Other authorised movement"),
    ]

    #: Which kinds add to the drawer and which remove from it. Explicit, so a
    #: newly added kind must be classified rather than defaulting either way.
    INFLOW_KINDS = frozenset({"CASH_IN", "FLOAT_TOP_UP"})
    OUTFLOW_KINDS = frozenset({"CASH_OUT", "SAFE_DROP", "PETTY_CASH", "BANKING"})

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="cash_movements")
    register_session = models.ForeignKey(
        RegisterSession, on_delete=models.PROTECT, related_name="cash_movements"
    )
    operator_shift = models.ForeignKey(
        OperatorShift, on_delete=models.PROTECT, null=True, blank=True, related_name="cash_movements"
    )
    kind = models.CharField(max_length=30, choices=KINDS)
    #: Always positive. Direction comes from `kind`, never from the sign.
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default="KES")
    reason_code = models.CharField(max_length=40, blank=True, default="")
    description = models.TextField(blank=True, default="")
    reference = models.CharField(max_length=120, blank=True, default="")
    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="chk_cash_movement_amount_positive"
            )
        ]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.kind} {self.currency} {self.amount}"

    @property
    def signed_amount(self) -> Decimal:
        """Effect on drawer cash. Positive adds, negative removes."""
        if self.kind in self.INFLOW_KINDS:
            return self.amount
        if self.kind in self.OUTFLOW_KINDS:
            return -self.amount
        # CORRECTION and OTHER_AUTHORISED_MOVEMENT carry no inherent direction;
        # they are reported but never silently folded into expected cash.
        return ZERO

    @property
    def affects_expected_cash(self) -> bool:
        return self.kind in self.INFLOW_KINDS | self.OUTFLOW_KINDS


class ShiftReport(TenantConsistencyMixin, TimestampedModel):
    """An X or Z report.

    The distinction is the whole point of this model and is enforced rather
    than documented:

    * **X** is an interim snapshot. It may be produced any number of times, it
      never closes the session, and it never resets a counter. Each one gets its
      own number and its own generation time, but they all share the session's
      period start, so an X is always cumulative from opening -- not a delta
      since the previous X.
    * **Z** is the final closure record. Exactly one may exist per register
      session, enforced by the partial unique index below rather than by a
      service check, because two concurrent closure requests would each find no
      existing Z and both proceed.

    `snapshot` holds the computed figures as they stood at generation. HQ reads
    that, never a recalculation: re-deriving a Z from today's transaction table
    would silently change a report that somebody already signed, printed and
    banked against.
    """

    tenant_relation_fields = ("register_session",)

    TYPE_X = "X"
    TYPE_Z = "Z"
    REPORT_TYPES = [(TYPE_X, "X report (interim)"), (TYPE_Z, "Z report (final closure)")]

    CLOSURE_NORMAL = "NORMAL"
    CLOSURE_FORCED = "FORCED"
    CLOSURE_TYPES = [(CLOSURE_NORMAL, "Normal"), (CLOSURE_FORCED, "Forced closure")]

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="shift_reports")
    register_session = models.ForeignKey(
        RegisterSession, on_delete=models.PROTECT, related_name="reports"
    )
    operator_shift = models.ForeignKey(
        OperatorShift, on_delete=models.PROTECT, null=True, blank=True, related_name="reports"
    )
    business_day = models.ForeignKey(BusinessDay, on_delete=models.PROTECT, related_name="shift_reports")

    report_type = models.CharField(max_length=1, choices=REPORT_TYPES)
    #: Branch/Register/BusinessDate/Type/Sequence. Immutable, and retained
    #: verbatim by every reprint.
    report_number = models.CharField(max_length=120)
    sequence = models.PositiveIntegerField()

    #: Always the session opening. An X is cumulative, never a delta.
    period_start = models.DateTimeField()
    generated_at = models.DateTimeField(default=timezone.now)
    generated_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")

    closure_type = models.CharField(max_length=10, choices=CLOSURE_TYPES, default=CLOSURE_NORMAL)
    closure_reason = models.TextField(blank=True, default="")
    approved_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    #: The frozen figures. Never recomputed for display.
    snapshot = models.JSONField(default=dict)
    #: Unresolved items the closure proceeded despite, listed on the report.
    exceptions = models.JSONField(default=list, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "report_number"], name="uq_shift_report_tenant_number"
            ),
            # Exactly one Z per register session. The index is the guard: two
            # concurrent closures would both see no Z and both proceed.
            models.UniqueConstraint(
                fields=["register_session"],
                condition=models.Q(report_type="Z"),
                name="uq_register_session_single_z",
            ),
        ]
        ordering = ["-generated_at"]

    def __str__(self) -> str:
        return self.report_number

    @property
    def is_final(self) -> bool:
        return self.report_type == self.TYPE_Z

    def save(self, *args, **kwargs):
        if self.pk:
            existing = (
                ShiftReport.all_objects.filter(pk=self.pk, tenant_id=self.tenant_id)
                .values("report_type", "snapshot", "report_number")
                .first()
            )
            if existing and existing["report_type"] == self.TYPE_Z:
                # A Z is a signed, printed, banked-against record. Corrections
                # go through an adjustment or a reversal, never through editing
                # the report somebody already acted on.
                if (
                    self.snapshot != existing["snapshot"]
                    or self.report_number != existing["report_number"]
                ):
                    raise ValidationError(
                        "A finalised Z report cannot be altered. "
                        "Record an adjustment or reversal instead."
                    )
        return super().save(*args, **kwargs)


class ShiftReportReprint(TenantConsistencyMixin, TimestampedModel):
    """A record that a report was printed again.

    Reprints are numbered but never renumbered: the original report number is
    retained so a reprint cannot be passed off as a separate closure.
    """

    tenant_relation_fields = ("report",)

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="report_reprints")
    report = models.ForeignKey(ShiftReport, on_delete=models.PROTECT, related_name="reprints")
    copy_number = models.PositiveIntegerField()
    reason = models.TextField()
    reprinted_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    reprinted_at = models.DateTimeField(default=timezone.now)
    printer = models.CharField(max_length=120, blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["report", "copy_number"], name="uq_report_reprint_copy"
            )
        ]
        ordering = ["report_id", "copy_number"]
