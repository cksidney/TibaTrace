"""Durable, independently approved POS enrolment; challenges are stored hashed."""
import hashlib
import secrets

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class PosActivationRequest(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("branch", "register", "requested_by")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT)
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT)
    register = models.ForeignKey("pos_shift.PosRegister", on_delete=models.PROTECT)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pos_activation_requests")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pos_activation_reviews", null=True, blank=True)
    device_id = models.CharField(max_length=120)
    device_fingerprint = models.CharField(max_length=255)
    device_name = models.CharField(max_length=160)
    device_type = models.CharField(max_length=32)
    app_version = models.CharField(max_length=40, blank=True)
    justification = models.TextField()
    state = models.CharField(max_length=24, default="SUBMITTED", db_index=True)
    rationale = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    challenge_hash = models.CharField(max_length=64, blank=True)
    challenge_expires_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    activation_expires_at = models.DateTimeField(null=True, blank=True)
    credential_hash = models.CharField(max_length=64, blank=True)
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "device_id"],
                condition=models.Q(state__in=["SUBMITTED", "APPROVED", "ACTIVATED"]),
                name="uq_pos_active_device_request",
            ),
        ]


def verify_device_credential(*, tenant_id, credential, device_id, fingerprint):
    """Approval is a durable server fact, not a client-supplied status flag."""
    if not credential or len(credential) > 8192 or not device_id or not fingerprint:
        raise PermissionDenied("Invalid activation credential.")
    try:
        claims = signing.loads(credential, salt="tibatrace.pos.activation.v1", max_age=366 * 86400)
        record = PosActivationRequest.all_objects.select_related("register").get(
            pk=claims["activation"], tenant_id=tenant_id,
        )
    except Exception as exc:
        # Invalid encodings/UUIDs/signatures must all fail closed without details.
        # Database outages also cannot become successful activation.
        raise PermissionDenied("Invalid activation credential.") from exc
    token_hash = hashlib.sha256(credential.encode()).hexdigest()
    if (record.state != "ACTIVATED" or not record.credential_hash
            or not record.activation_expires_at or record.activation_expires_at <= timezone.now()
            or not secrets.compare_digest(record.credential_hash, token_hash)
            or str(record.tenant_id) != claims.get("tenant")
            or str(record.branch_id) != claims.get("branch")
            or record.device_id != claims.get("device") or record.device_fingerprint != claims.get("fingerprint")
            or record.device_id != device_id or record.device_fingerprint != fingerprint
            or record.register.device_id != record.device_id):
        raise PermissionDenied("Device activation is revoked, expired or mismatched.")
    return record

