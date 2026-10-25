"""Tenant/branch-owned DHA configuration and encrypted workflow journals."""
from django.conf import settings
from django.db import models

from apps.core.models import TenantConsistencyMixin, TenantScopedModel


class DhaConnection(TenantConsistencyMixin, TenantScopedModel):
    tenant_relation_fields = ("branch",)
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT)
    environment = models.CharField(max_length=12, choices=[("SANDBOX", "Sandbox"), ("PRODUCTION", "Production")])
    state = models.CharField(max_length=16, default="DISABLED", choices=[
        (s, s) for s in ("DISABLED", "SANDBOX", "ACTIVE", "SUSPENDED")])
    # Only non-secret settings; values live in environment/secret-manager injection.
    configuration = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    validated_revision = models.PositiveIntegerField(default=0)
    validated_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "branch", "environment"], name="uq_dha_branch_env")]


class DhaVisit(TenantConsistencyMixin, TenantScopedModel):
    tenant_relation_fields = ("connection", "patient", "actor")
    connection = models.ForeignKey(DhaConnection, on_delete=models.PROTECT, related_name="visits")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    # CR ID, PUID, consent/visit IDs and tokens are encrypted together.
    protected_context = models.TextField(blank=True)
    state = models.CharField(max_length=20, default="PENDING")
    # Non-secret opaque local identifier used for lookup, never national identifiers.
    consent_expires_at = models.DateTimeField(null=True, blank=True)


class DhaExchange(TenantConsistencyMixin, TenantScopedModel):
    tenant_relation_fields = ("connection", "visit", "actor")
    connection = models.ForeignKey(DhaConnection, on_delete=models.PROTECT, related_name="exchanges")
    visit = models.ForeignKey(DhaVisit, null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operation = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)
    connection_revision = models.PositiveIntegerField()
    protected_request = models.TextField()
    protected_response = models.TextField(blank=True)
    state = models.CharField(max_length=20, default="PENDING")
    attempts = models.PositiveIntegerField(default=0)
    http_status = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["connection", "idempotency_key"], name="uq_dha_exchange_key")]
        indexes = [models.Index(fields=["state", "next_attempt_at"], name="ix_dha_exchange_due")]


class DhaCallback(TenantConsistencyMixin, TenantScopedModel):
    tenant_relation_fields = ("connection",)
    connection = models.ForeignKey(DhaConnection, on_delete=models.PROTECT)
    digest = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=20)
    protected_payload = models.TextField()
    # Notification is retained for reconciliation; it never pays/approves a local claim.
    state = models.CharField(max_length=20, default="RECEIVED")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["connection", "digest"], name="uq_dha_callback_digest")]
