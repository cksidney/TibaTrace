"""Authoritative device requests, review, single-use enrolment and revocation."""
import hashlib
import secrets
from datetime import timedelta

from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.audit.service import log_audit
from apps.core.permissions import PlatformOwnerRequired
from apps.pos_shift.models import PosRegister
from apps.tenancy.models import Tenant

from .pos_activation import PosActivationRequest, verify_device_credential


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def payload(record):
    return {
        "id": str(record.pk), "tenantId": str(record.tenant_id), "branchId": str(record.branch_id),
        "deviceId": record.device_id, "deviceFingerprint": record.device_fingerprint,
        "deviceName": record.device_name, "deviceType": record.device_type,
        "requestedRegister": record.register.code, "register": record.register.code,
        "requestingUserId": str(record.requested_by_id), "requester": record.requested_by.username,
        "requesterEmailSnapshot": record.requested_by.email, "requesterRole": "REQUESTER",
        "businessJustification": record.justification, "justification": record.justification,
        "state": record.state, "appVersion": record.app_version,
        "submittedAt": record.created_at.isoformat(), "approvalRationale": record.rationale,
        "activationExpiry": record.activation_expires_at.isoformat() if record.activation_expires_at else None,
        "requestedPeriodDays": 365, "requestedCapabilities": [], "supportingAttachments": [],
        "correlationId": str(record.pk), "osName": "", "osVersion": "",
    }


class RequestInput(serializers.Serializer):
    tenant_id = serializers.UUIDField(required=False)
    branch_id = serializers.UUIDField()
    requested_register = serializers.CharField(max_length=120)
    device_id = serializers.CharField(max_length=120)
    device_fingerprint = serializers.CharField(min_length=16, max_length=255)
    device_name = serializers.CharField(max_length=160)
    device_type = serializers.ChoiceField(choices=["DESKTOP_WINDOWS", "MOBILE_ANDROID", "TABLET", "WORKSTATION"])
    app_version = serializers.CharField(max_length=40, required=False, default="")
    business_justification = serializers.CharField(min_length=10, max_length=2000)


class TenantPosActivationViewSet(GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = RequestInput

    def _scope(self, capability="tenant.pos_activation.view"):
        tenant_id = getattr(self.request, "tenant_id", None) or self.request.user.tenant_id
        if not tenant_id:
            raise ValidationError("Select a tenant workspace.")
        if not any(self.request.user.has_capability(cap, tenant_id=tenant_id) for cap in [capability, "identity.manage"]):
            raise PermissionDenied("Tenant activation authority is required.")
        return tenant_id

    def get_queryset(self):
        return PosActivationRequest.all_objects.filter(tenant_id=self._scope()).select_related("register", "requested_by")

    def list(self, request):
        return Response([payload(row) for row in self.get_queryset().order_by("-created_at")[:200]])

    @transaction.atomic
    def create(self, request):
        tenant_id = self._scope("tenant.pos_activation.request")
        incoming = RequestInput(data=request.data)
        incoming.is_valid(raise_exception=True)
        data = incoming.validated_data
        if str(data.get("tenant_id", tenant_id)) != str(tenant_id):
            raise PermissionDenied("The requested tenant is outside this workspace.")
        # Serialize requests across registers too: one device cannot race into two queues.
        Tenant.objects.select_for_update().get(pk=tenant_id)
        register = PosRegister.all_objects.select_for_update().filter(
            tenant_id=tenant_id, location_id=data["branch_id"], code=data["requested_register"]
        ).first()
        if register is None:
            raise ValidationError("Select a register belonging to this tenant and branch.")
        if register.device_id and register.device_id != data["device_id"]:
            raise ValidationError("This register belongs to a different device; request a governed transfer.")
        if PosActivationRequest.all_objects.filter(tenant_id=tenant_id, device_id=data["device_id"],
                                                 state__in=["SUBMITTED", "APPROVED", "ACTIVATED"]).exists():
            raise ValidationError("This device already has a pending or active enrolment.")
        record = PosActivationRequest.all_objects.create(
            tenant_id=tenant_id, branch_id=data["branch_id"], register=register, requested_by=request.user,
            device_id=data["device_id"], device_fingerprint=data["device_fingerprint"],
            device_name=data["device_name"], device_type=data["device_type"],
            app_version=data["app_version"], justification=data["business_justification"],
        )
        self._audit(record, "POS_ACTIVATION_REQUESTED")
        return Response(payload(record), status=201)

    def _audit(self, record, action_name):
        log_audit(tenant_id=record.tenant_id, actor_id=self.request.user.pk, action=action_name,
                  model_name="platform.PosActivationRequest", object_id=str(record.pk),
                  metadata={"state": record.state, "device_id": record.device_id, "rationale": record.rationale})

    def _locked(self, pk):
        try:
            record = self.get_queryset().select_for_update().filter(pk=pk).first()
        except (ValueError, DjangoValidationError):
            raise NotFound("Activation request not found.")
        if record is None:
            raise NotFound("Activation request not found.")
        return record

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def enrol(self, request, pk=None):
        record = self._locked(pk)
        code = str(request.data.get("challenge_code", ""))
        if (record.state != "APPROVED" or not record.challenge_hash or not record.challenge_expires_at
                or record.challenge_expires_at <= timezone.now() or not secrets.compare_digest(digest(code), record.challenge_hash)):
            raise ValidationError("The enrolment challenge is invalid, expired or already used.")
        if (request.data.get("device_id") != record.device_id
                or request.data.get("device_fingerprint") != record.device_fingerprint):
            raise PermissionDenied("Device identity does not match the approved request.")
        register = PosRegister.all_objects.select_for_update().get(pk=record.register_id, tenant_id=record.tenant_id)
        if register.device_id and register.device_id != record.device_id:
            raise ValidationError("Register assignment changed after approval.")
        if PosRegister.all_objects.filter(tenant_id=record.tenant_id, device_id=record.device_id).exclude(pk=register.pk).exists():
            raise ValidationError("Device has another register assignment.")
        register.device_id = record.device_id
        register.save(update_fields=["device_id", "updated_at"])
        now = timezone.now()
        record.state = "ACTIVATED"
        record.activated_at = now
        record.activation_expires_at = now + timedelta(days=365)
        credential = signing.dumps({"activation": str(record.pk), "tenant": str(record.tenant_id),
                                    "branch": str(record.branch_id),
                                    "device": record.device_id, "fingerprint": record.device_fingerprint,
                                    "nonce": secrets.token_urlsafe(32)}, salt="tibatrace.pos.activation.v1")
        record.credential_hash = digest(credential)
        record.challenge_hash = ""
        record.save()
        self._audit(record, "POS_DEVICE_ENROLLED")
        return Response({"activationId": str(record.pk), "tenantId": str(record.tenant_id),
                         "branchId": str(record.branch_id), "deviceId": record.device_id,
                         "deviceFingerprint": record.device_fingerprint, "appVersion": record.app_version,
                         "minimumRequiredBuild": "0", "state": record.state, "issuedAt": now.isoformat(),
                         "expiresAt": record.activation_expires_at.isoformat(), "signedToken": credential,
                         "isRevoked": False})

    @action(detail=False, methods=["post"], url_path="validate")
    def validate_credential(self, request):
        """Re-check durable approval and revocation; never trust the client DTO."""
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        from django.core.exceptions import PermissionDenied as DjangoPermissionDenied

        try:
            record = verify_device_credential(tenant_id=tenant_id, credential=str(request.data.get("signed_token", "")),
                                             device_id=request.data.get("device_id"), fingerprint=request.data.get("device_fingerprint"))
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc
        return Response({"valid": True, "activationId": str(record.pk), "branchId": str(record.branch_id),
                         "expiresAt": record.activation_expires_at.isoformat()})


class PlatformPosActivationViewSet(TenantPosActivationViewSet):
    permission_classes = [IsAuthenticated, PlatformOwnerRequired]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request):
        raise MethodNotAllowed("POST", detail="Submit requests from the tenant activation endpoint.")

    def get_queryset(self):
        qs = PosActivationRequest.all_objects.select_related("register", "requested_by")
        scope = self.request.query_params.get("tenant_id") or getattr(self.request, "tenant_id", None)
        if scope:
            try:
                qs = qs.filter(tenant_id=Tenant.objects.get(pk=scope).pk)
            except (Tenant.DoesNotExist, ValueError, DjangoValidationError):
                raise ValidationError("Unknown tenant workspace.")
        return qs

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def approve(self, request, pk=None):
        return self._decide("APPROVED", pk)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reject(self, request, pk=None):
        return self._decide("REJECTED", pk)

    def _decide(self, state, pk):
        record = self._locked(pk)
        if record.state != "SUBMITTED":
            raise ValidationError("Only submitted requests can be reviewed.")
        if record.requested_by_id == self.request.user.pk:
            raise PermissionDenied("Requesters cannot approve or reject their own requests.")
        rationale = str(self.request.data.get("rationale") or self.request.data.get("approval_rationale") or "").strip()
        if len(rationale) < 10 or len(rationale) > 2000:
            raise ValidationError("Record a review rationale of 10–2000 characters.")
        record.state = state
        record.rationale = rationale
        record.reviewed_by = self.request.user
        record.reviewed_at = timezone.now()
        challenge = ""
        if state == "APPROVED":
            challenge = secrets.token_urlsafe(24)
            record.challenge_hash = digest(challenge)
            record.challenge_expires_at = timezone.now() + timedelta(minutes=15)
        record.save()
        self._audit(record, f"POS_ACTIVATION_{state}")
        result = payload(record)
        if challenge:
            result["challengeCode"] = challenge
            result["challengeExpiresAt"] = record.challenge_expires_at.isoformat()
        return Response(result)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def revoke(self, request, pk=None):
        record = self._locked(pk)
        rationale = str(request.data.get("rationale", "")).strip()
        if len(rationale) < 10:
            raise ValidationError("A revocation rationale is required.")
        record.state = "REVOKED"
        record.rationale = rationale[:2000]
        record.challenge_hash = ""
        record.credential_hash = ""
        record.save()
        self._audit(record, "POS_ACTIVATION_REVOKED")
        return Response(payload(record))
