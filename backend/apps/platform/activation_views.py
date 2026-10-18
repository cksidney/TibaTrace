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
from apps.pos_shift.models import PosRegister, RegisterSession
from apps.pos_shift.reporting import ShiftReportService
from apps.tenancy.models import Tenant

from .pos_activation import PosActivationRequest, verify_device_credential

RESERVED_STATES = ["SUBMITTED", "APPROVED", "ACTIVATED", "SUSPENDED"]


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
        "challengeExpiresAt": record.challenge_expires_at.isoformat() if record.challenge_expires_at else None,
        "challengeAvailable": bool(record.challenge_hash and record.challenge_expires_at and record.challenge_expires_at > timezone.now()),
        "credentialExpired": bool(record.activation_expires_at and record.activation_expires_at <= timezone.now()),
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
        capabilities = [capability, "identity.manage"]
        if capability == "tenant.pos_activation.view":
            capabilities.append("tenant.pos_activation.request")
        if not any(self.request.user.has_capability(cap, tenant_id=tenant_id) for cap in capabilities):
            raise PermissionDenied("Tenant activation authority is required.")
        return tenant_id

    def get_queryset(self):
        return PosActivationRequest.all_objects.filter(tenant_id=self._scope()).select_related("register", "requested_by")

    def list(self, request):
        rows = self.get_queryset()
        if request.query_params.get("device_id"):
            rows = rows.filter(device_id=request.query_params["device_id"])
        return Response([payload(row) for row in rows.order_by("-created_at")[:200]], headers={"Cache-Control": "no-store"})

    @action(detail=False, methods=["get"], url_path="options")
    def options_for_request(self, request):
        tenant_id = self._scope("tenant.pos_activation.request")
        from apps.organizations.models import Location

        reserved = set(PosActivationRequest.all_objects.filter(tenant_id=tenant_id, state__in=RESERVED_STATES).values_list("register_id", flat=True))
        return Response({
            "branches": list(Location.all_objects.filter(tenant_id=tenant_id, status="ACTIVE").order_by("name").values("id", "code", "name")),
            "registers": [{"id": str(row.pk), "branchId": str(row.location_id), "code": row.code, "name": row.name,
                           "available": row.location.status == "ACTIVE" and row.accepts_opening and not row.device_id and row.pk not in reserved}
                          for row in PosRegister.all_objects.filter(tenant_id=tenant_id).order_by("code")],
        }, headers={"Cache-Control": "no-store"})

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
            tenant_id=tenant_id, location_id=data["branch_id"], location__status="ACTIVE", code=data["requested_register"]
        ).first()
        if register is None:
            raise ValidationError("Select a register belonging to this tenant and branch.")
        if not register.accepts_opening:
            raise ValidationError("This register is not available for a new activation.")
        if register.device_id and register.device_id != data["device_id"]:
            raise ValidationError("This register belongs to a different device. Close its session, revoke its activation and release its assignment before replacement.")
        if PosActivationRequest.all_objects.filter(tenant_id=tenant_id, device_id=data["device_id"],
                                                 state__in=RESERVED_STATES).exists():
            raise ValidationError("This device already has a pending, active or suspended enrolment. Ask the platform owner to renew or recover it.")
        if PosActivationRequest.all_objects.filter(tenant_id=tenant_id, register=register, state__in=RESERVED_STATES).exists():
            raise ValidationError("This register already has a pending, active or suspended activation.")
        if PosRegister.all_objects.filter(tenant_id=tenant_id, device_id=data["device_id"]).exclude(pk=register.pk).exists():
            raise ValidationError("This installation is already assigned to another register.")
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
            tenant_id = self.get_queryset().filter(pk=pk).values_list("tenant_id", flat=True).first()
            if tenant_id:
                Tenant.objects.select_for_update().get(pk=tenant_id)
            record = self.get_queryset().select_for_update().filter(pk=pk).first()
        except (ValueError, DjangoValidationError):
            raise NotFound("Activation request not found.")
        if record is None:
            raise NotFound("Activation request not found.")
        return record

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def enrol(self, request, pk=None):
        self._scope("tenant.pos_activation.request")
        record = self._locked(pk)
        code = str(request.data.get("challenge_code", ""))
        if (record.state not in {"APPROVED", "ACTIVATED"} or not record.reviewed_by_id or record.reviewed_by_id == record.requested_by_id
                or not record.challenge_hash or not record.challenge_expires_at
                or record.challenge_expires_at <= timezone.now() or not secrets.compare_digest(digest(code), record.challenge_hash)):
            raise ValidationError("The enrolment challenge is invalid, expired or already used.")
        if (request.data.get("device_id") != record.device_id
                or request.data.get("device_fingerprint") != record.device_fingerprint):
            raise PermissionDenied("Device identity does not match the approved request.")
        register = PosRegister.all_objects.select_for_update().get(pk=record.register_id, tenant_id=record.tenant_id)
        if register.location_id != record.branch_id:
            raise ValidationError("Register branch changed after approval.")
        if record.state == "APPROVED":
            self._assert_register_ready_for_first_enrolment(register)
        if PosActivationRequest.all_objects.filter(tenant_id=record.tenant_id, register=register, state__in=RESERVED_STATES).exclude(pk=record.pk).exists():
            raise ValidationError("Register has another pending or active activation.")
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
        record.challenge_expires_at = None
        record.save()
        self._audit(record, "POS_DEVICE_ENROLLED")
        return Response({"activationId": str(record.pk), "tenantId": str(record.tenant_id),
                         "branchId": str(record.branch_id), "deviceId": record.device_id,
                         "deviceFingerprint": record.device_fingerprint, "appVersion": record.app_version,
                         "minimumRequiredBuild": "0", "state": record.state, "issuedAt": now.isoformat(),
                         "expiresAt": record.activation_expires_at.isoformat(), "signedToken": credential,
                         "isRevoked": False}, headers={"Cache-Control": "no-store"})

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

    @staticmethod
    def _assert_register_ready_for_first_enrolment(register):
        if register.location.status != "ACTIVE" or not register.accepts_opening:
            raise ValidationError("The branch or register is no longer available. Close and reconcile it before first enrolment.")
        if RegisterSession.all_objects.filter(tenant_id=register.tenant_id, register=register, state__in=["OPEN", "CLOSING"]).exists():
            raise ValidationError("Close and reconcile the register before first enrolment.")
        previous = RegisterSession.all_objects.filter(tenant_id=register.tenant_id, register=register).order_by("-opened_at").first()
        if previous and ShiftReportService.final_report(session=previous) is None:
            raise ValidationError("The last register session requires a final Z report before first enrolment.")


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
        self._independent(record)
        if state == "APPROVED":
            register = PosRegister.all_objects.select_for_update().get(pk=record.register_id, tenant_id=record.tenant_id)
            if register.location_id != record.branch_id:
                raise ValidationError("The requested register branch has changed. Reject this request and submit a new one.")
            self._assert_register_ready_for_first_enrolment(register)
        rationale = self._rationale()
        record.state = state
        record.rationale = rationale
        record.reviewed_by = self.request.user
        record.reviewed_at = timezone.now()
        challenge = self._challenge(record) if state == "APPROVED" else ""
        record.save()
        self._audit(record, f"POS_ACTIVATION_{state}")
        result = payload(record)
        if challenge:
            result["challengeCode"] = challenge
        return Response(result, headers={"Cache-Control": "no-store"})

    def _rationale(self):
        rationale = str(self.request.data.get("rationale") or self.request.data.get("approval_rationale") or "").strip()
        if len(rationale) < 10 or len(rationale) > 2000:
            raise ValidationError("Record a review rationale of 10–2000 characters.")
        return rationale

    def _independent(self, record):
        if record.requested_by_id == self.request.user.pk:
            raise PermissionDenied("A different platform owner must review this activation.")

    @staticmethod
    def _challenge(record):
        challenge = secrets.token_urlsafe(24)
        record.challenge_hash = digest(challenge)
        record.challenge_expires_at = timezone.now() + timedelta(minutes=15)
        return challenge

    @action(detail=True, methods=["post"], url_path="issue-code")
    @transaction.atomic
    def issue_code(self, request, pk=None):
        record = self._locked(pk)
        self._independent(record)
        if record.state not in {"APPROVED", "ACTIVATED"}:
            raise ValidationError("Only approved or activated installations can receive a recovery or renewal code.")
        register = PosRegister.all_objects.select_for_update().get(pk=record.register_id, tenant_id=record.tenant_id)
        if register.location_id != record.branch_id or (register.device_id and register.device_id != record.device_id):
            raise ValidationError("The approved register assignment changed. Review the replacement process.")
        record.rationale = self._rationale()
        record.reviewed_by = request.user
        record.reviewed_at = timezone.now()
        code = self._challenge(record)
        record.save()
        self._audit(record, "POS_ACTIVATION_CODE_REISSUED")
        return Response({**payload(record), "challengeCode": code}, headers={"Cache-Control": "no-store"})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def suspend(self, request, pk=None):
        record = self._locked(pk)
        if record.state != "ACTIVATED":
            raise ValidationError("Only an activated installation can be suspended.")
        record.rationale = self._rationale()
        record.state = "SUSPENDED"
        record.challenge_hash = ""
        record.challenge_expires_at = None
        record.save()
        self._audit(record, "POS_ACTIVATION_SUSPENDED")
        return Response(payload(record))

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def resume(self, request, pk=None):
        record = self._locked(pk)
        self._independent(record)
        if record.state != "SUSPENDED":
            raise ValidationError("Only a suspended installation can be resumed.")
        register = PosRegister.all_objects.select_for_update().get(pk=record.register_id, tenant_id=record.tenant_id)
        if register.device_id != record.device_id or register.location_id != record.branch_id:
            raise ValidationError("Register assignment changed. Review the replacement process before resuming.")
        record.rationale = self._rationale()
        record.state = "ACTIVATED"
        record.save()
        self._audit(record, "POS_ACTIVATION_RESUMED")
        return Response(payload(record))

    @action(detail=True, methods=["post"], url_path="release-register")
    @transaction.atomic
    def release_register(self, request, pk=None):
        record = self._locked(pk)
        self._independent(record)
        if record.state != "REVOKED":
            raise ValidationError("Revoke the old installation before releasing its register.")
        record.rationale = self._rationale()
        register = PosRegister.all_objects.select_for_update().get(pk=record.register_id, tenant_id=record.tenant_id)
        if register.device_id != record.device_id:
            raise ValidationError("The register no longer belongs to this installation.")
        if not register.accepts_opening or RegisterSession.all_objects.filter(tenant_id=record.tenant_id, register=register, state__in=["OPEN", "CLOSING"]).exists():
            raise ValidationError("Close and reconcile the register before replacing the device.")
        previous = RegisterSession.all_objects.filter(tenant_id=record.tenant_id, register=register).order_by("-opened_at").first()
        if previous and ShiftReportService.final_report(session=previous) is None:
            raise ValidationError("The last register session requires a final Z report.")
        if PosActivationRequest.all_objects.filter(tenant_id=record.tenant_id, register=register, state__in=RESERVED_STATES).exists():
            raise ValidationError("The register has another pending or active activation.")
        register.device_id = ""
        register.save(update_fields=["device_id", "updated_at"])
        record.save()
        self._audit(record, "POS_REGISTER_ASSIGNMENT_RELEASED")
        return Response(payload(record))

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def revoke(self, request, pk=None):
        record = self._locked(pk)
        rationale = self._rationale()
        record.state = "REVOKED"
        record.rationale = rationale[:2000]
        record.challenge_hash = ""
        record.challenge_expires_at = None
        record.credential_hash = ""
        record.save()
        self._audit(record, "POS_ACTIVATION_REVOKED")
        return Response(payload(record))
