"""Integration platform API views.

All Platform Owner surfaces. No tenant-facing integration management.
Providers cannot be activated without explicit Platform Owner state advance.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.audit.service import log_audit, log_platform_audit
from apps.core.permissions import PlatformOwnerRequired
from apps.integrations.models import (
    ActivationState,
    IntegrationDeadLetter,
    IntegrationMessage,
    ProviderActivationDecision,
    ProviderActivationRequest,
    ProviderConfiguration,
    ProviderCredentialReference,
    ProviderEndpoint,
    ProviderHealthSnapshot,
)
from apps.integrations.serializers import (
    ActivationAdvanceSerializer,
    DeadLetterReplaySerializer,
    IntegrationDeadLetterSerializer,
    IntegrationMessageSerializer,
    ProviderActivationRequestSerializer,
    ProviderConfigurationSerializer,
    ProviderCredentialReferenceSerializer,
    ProviderEndpointSerializer,
    ProviderHealthSnapshotSerializer,
)

logger = logging.getLogger(__name__)

# Valid activation state transitions (Platform Owner gate)
VALID_TRANSITIONS = {
    ActivationState.REQUESTED: [ActivationState.UNDER_REVIEW, ActivationState.REJECTED],
    ActivationState.UNDER_REVIEW: [ActivationState.SECURITY_REVIEW, ActivationState.SANDBOX_CONFIGURED, ActivationState.REJECTED],
    ActivationState.SECURITY_REVIEW: [ActivationState.SANDBOX_CONFIGURED, ActivationState.REJECTED],
    ActivationState.SANDBOX_CONFIGURED: [ActivationState.SANDBOX_TESTING, ActivationState.REJECTED],
    ActivationState.SANDBOX_TESTING: [ActivationState.SANDBOX_PASSED, ActivationState.SANDBOX_CONFIGURED, ActivationState.REJECTED],
    ActivationState.SANDBOX_PASSED: [ActivationState.CERTIFICATION_REVIEW, ActivationState.SECURITY_APPROVED, ActivationState.REJECTED],
    ActivationState.CERTIFICATION_REVIEW: [ActivationState.SECURITY_APPROVED, ActivationState.PRODUCTION_APPROVED, ActivationState.REJECTED],
    ActivationState.SECURITY_APPROVED: [ActivationState.PRODUCTION_APPROVED, ActivationState.REJECTED],
    ActivationState.PRODUCTION_APPROVED: [ActivationState.ACTIVE, ActivationState.REJECTED],
    ActivationState.ACTIVE: [ActivationState.SUSPENDED, ActivationState.REVOKED, ActivationState.DECOMMISSIONED],
    ActivationState.SUSPENDED: [ActivationState.ACTIVE, ActivationState.REVOKED, ActivationState.DECOMMISSIONED],
}


class ProviderConfigurationViewSet(ModelViewSet):
    """Platform Owner: manage provider configurations."""

    permission_classes = [IsAuthenticated, PlatformOwnerRequired]
    serializer_class = ProviderConfigurationSerializer
    queryset = ProviderConfiguration.all_objects.prefetch_related(
        "health_snapshots", "endpoints", "credential_references"
    ).all()

    def perform_create(self, serializer):
        with transaction.atomic():
            provider = serializer.save()
            log_platform_audit(
                action="PROVIDER_CONFIGURATION_CREATED",
                model_name="ProviderConfiguration",
                object_id=provider.id,
                actor_id=self.request.user.id,
                metadata={"provider_type": provider.provider_type, "environment": provider.environment},
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            provider = serializer.save()
            log_platform_audit(
                action="PROVIDER_CONFIGURATION_UPDATED",
                model_name="ProviderConfiguration",
                object_id=provider.id,
                actor_id=self.request.user.id,
                metadata={
                    "provider_type": provider.provider_type,
                    "environment": provider.environment,
                    "display_name": provider.display_name,
                    "changed_fields": sorted(serializer.validated_data.keys()),
                },
            )

    def perform_destroy(self, instance):
        raise MethodNotAllowed(
            "DELETE",
            detail="Provider history is retained. Use the governed decommission transition instead.",
        )

    @action(detail=True, methods=["get"], url_path="health")
    def health(self, request, pk=None):
        provider = self.get_object()
        snapshots = ProviderHealthSnapshot.objects.filter(
            provider=provider
        ).order_by("-checked_at")[:10]
        return Response(ProviderHealthSnapshotSerializer(snapshots, many=True).data)

    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request, pk=None):
        provider = self.get_object()
        msgs = IntegrationMessage.all_objects.filter(
            provider=provider
        ).order_by("-created_at")[:100]
        return Response(IntegrationMessageSerializer(msgs, many=True).data)

    @action(detail=True, methods=["get"], url_path="dead-letters")
    def dead_letters(self, request, pk=None):
        provider = self.get_object()
        dlqs = IntegrationDeadLetter.objects.filter(
            message__provider=provider,
            replayed_at__isnull=True,
        ).select_related("message").order_by("-dead_lettered_at")[:50]
        return Response(IntegrationDeadLetterSerializer(dlqs, many=True).data)

    @action(detail=True, methods=["post"], url_path="test-connectivity")
    def test_connectivity(self, request, pk=None):
        """Check endpoint TLS allow-list policy without sending a network request."""
        provider = self.get_object()
        endpoints = provider.endpoints.filter(is_active=True)
        results = []
        for ep in endpoints:
            host = urlsplit(ep.base_url).hostname
            is_allowed = bool(
                host
                and host.lower().rstrip(".")
                in {str(allowed).lower().rstrip(".") for allowed in ep.allowed_hosts}
            )
            results.append({
                "endpoint_name": ep.name,
                "base_url": ep.base_url,
                "allowed_hosts": ep.allowed_hosts,
                "is_allowed_hosts_configured": is_allowed,
                "status": "TLS_ALLOW_LIST_CONFIGURED" if is_allowed else "ALLOW_LIST_MISMATCH_FAIL_CLOSED",
            })
        return Response({"provider": provider.provider_type, "endpoints": results})

    @action(detail=True, methods=["get", "post"], url_path="endpoints")
    @transaction.atomic
    def endpoints(self, request, pk=None):
        """List or configure an HTTPS endpoint with an explicit TLS host allow-list."""
        provider = self.get_object()
        if request.method == "GET":
            items = provider.endpoints.all().order_by("name")
            return Response(ProviderEndpointSerializer(items, many=True).data)

        serializer = ProviderEndpointSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        parsed_url = urlsplit(values["base_url"])
        if parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
            return Response(
                {"base_url": "Use an HTTPS endpoint without embedded credentials."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        allowed_hosts = [str(host).strip().lower().rstrip(".") for host in values.get("allowed_hosts", [])]
        if any(not re.fullmatch(r"(?:[a-z0-9-]+\.)*[a-z0-9-]+", host) for host in allowed_hosts):
            return Response(
                {"allowed_hosts": "Enter host names only, without protocols, paths, wildcards, or credentials."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if parsed_url.hostname.lower().rstrip(".") not in allowed_hosts:
            return Response(
                {"allowed_hosts": "The endpoint host must be present in the TLS allow-list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        endpoint, created = ProviderEndpoint.objects.update_or_create(
            provider=provider,
            name=values["name"],
            defaults={
                "base_url": values["base_url"],
                "allowed_hosts": allowed_hosts,
                "is_active": values.get("is_active", False),
            },
        )
        log_platform_audit(
            action="PROVIDER_ENDPOINT_CONFIGURED",
            model_name="ProviderEndpoint",
            object_id=endpoint.id,
            actor_id=request.user.id,
            metadata={
                "provider_id": str(provider.id),
                "provider_type": provider.provider_type,
                "endpoint_name": endpoint.name,
                "host": parsed_url.hostname.lower(),
                "allowed_hosts": allowed_hosts,
                "is_active": endpoint.is_active,
            },
        )
        return Response(
            ProviderEndpointSerializer(endpoint).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "post"], url_path="credential-references")
    @transaction.atomic
    def credential_references(self, request, pk=None):
        """Record non-secret credential references; raw credential values are rejected."""
        provider = self.get_object()
        if request.method == "GET":
            items = provider.credential_references.all().order_by("credential_type")
            return Response(ProviderCredentialReferenceSerializer(items, many=True).data)

        serializer = ProviderCredentialReferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        reference = values["reference"].strip()
        is_reference_name = bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,127}", reference))
        is_secret_manager_path = bool(
            re.fullmatch(r"(?:vault|secretmanager|aws-secretsmanager)://[A-Za-z0-9_./-]{2,400}", reference)
        )
        if not (is_reference_name or is_secret_manager_path):
            return Response(
                {"reference": "Enter a secret-manager path or environment variable name, never a credential value."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_configured = values.get("is_configured", False)
        credential, created = ProviderCredentialReference.objects.update_or_create(
            provider=provider,
            credential_type=values["credential_type"],
            defaults={
                "reference": reference,
                "is_configured": is_configured,
                "configured_at": timezone.now() if is_configured else None,
                "configured_by": request.user if is_configured else None,
            },
        )
        log_platform_audit(
            action="PROVIDER_CREDENTIAL_REFERENCE_CONFIGURED",
            model_name="ProviderCredentialReference",
            object_id=credential.id,
            actor_id=request.user.id,
            metadata={
                "provider_id": str(provider.id),
                "provider_type": provider.provider_type,
                "credential_type": credential.credential_type,
                "reference": credential.reference,
                "is_configured": credential.is_configured,
            },
        )
        return Response(
            ProviderCredentialReferenceSerializer(credential).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="enable-kill-switch")
    def enable_kill_switch(self, request, pk=None):
        """Immediately suspend all operations for this provider (Security Emergency Kill Switch)."""
        provider = self.get_object()
        reason = str(request.data.get("reason", "")).strip()
        if len(reason) < 10:
            return Response(
                {"reason": "Record at least 10 characters describing the incident or suspension reason."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            active_request = ProviderActivationRequest.objects.filter(
                provider=provider,
                state=ActivationState.ACTIVE,
            ).order_by("-requested_at").first()
            provider.activation_state = ActivationState.SUSPENDED
            provider.suspended_at = timezone.now()
            provider.truth_label = (
                "DISABLED_IN_PRODUCTION"
                if provider.environment == "PRODUCTION"
                else "ADAPTER_SCAFFOLDED_NOT_CONNECTED"
            )
            provider.save(update_fields=["activation_state", "suspended_at", "truth_label", "updated_at"])

            decision_id = None
            if active_request:
                active_request.state = ActivationState.SUSPENDED
                active_request.notes = reason
                active_request.save(update_fields=["state", "notes", "updated_at"])
                decision = ProviderActivationDecision.objects.create(
                    activation_request=active_request,
                    decided_by=request.user,
                    from_state=ActivationState.ACTIVE,
                    to_state=ActivationState.SUSPENDED,
                    decision_notes=reason,
                    truth_label=provider.truth_label,
                )
                decision_id = str(decision.id)

            log_platform_audit(
                action="PROVIDER_KILL_SWITCH_ACTIVATED",
                model_name="ProviderConfiguration",
                object_id=provider.id,
                actor_id=request.user.id,
                metadata={
                    "reason": reason,
                    "provider_type": provider.provider_type,
                    "activation_request_id": str(active_request.id) if active_request else None,
                    "decision_id": decision_id,
                    "truth_label": provider.truth_label,
                },
            )
        return Response(
            {"detail": f"Kill switch activated for provider {provider.provider_type}.", "provider": ProviderConfigurationSerializer(provider).data},
            status=status.HTTP_200_OK,
        )


class ProviderActivationRequestViewSet(ModelViewSet):
    """Platform Owner: manage activation requests."""

    permission_classes = [IsAuthenticated, PlatformOwnerRequired]
    serializer_class = ProviderActivationRequestSerializer
    queryset = ProviderActivationRequest.objects.select_related("provider", "requested_by").prefetch_related("decisions__decided_by").all()

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="advance")
    @transaction.atomic
    def advance(self, request, pk=None):
        """Advance an activation request to the next state.

        Enforces the Platform Owner activation gate.
        Only valid transitions (as per VALID_TRANSITIONS) are allowed.
        """
        activation_req = self.get_object()
        serializer = ActivationAdvanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        to_state = serializer.validated_data["to_state"]
        notes = serializer.validated_data.get("notes", "")

        allowed = VALID_TRANSITIONS.get(activation_req.state, [])
        if to_state not in allowed:
            return Response(
                {
                    "detail": (
                        f"Cannot transition from '{activation_req.state}' to '{to_state}'. "
                        f"Allowed targets: {allowed}"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if to_state == ActivationState.SANDBOX_CONFIGURED:
            provider = activation_req.provider
            has_allowlisted_endpoint = any(
                endpoint.is_active
                and endpoint.base_url.startswith("https://")
                and urlsplit(endpoint.base_url).hostname
                and urlsplit(endpoint.base_url).hostname.lower().rstrip(".")
                in {str(host).lower().rstrip(".") for host in endpoint.allowed_hosts}
                for endpoint in provider.endpoints.all()
            )
            has_configured_reference = provider.credential_references.filter(is_configured=True).exists()
            if not has_allowlisted_endpoint or not has_configured_reference:
                return Response(
                    {
                        "detail": "Configure an active HTTPS endpoint with a matching TLS allow-list and at least one configured credential reference before sandbox configuration approval."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        from_state = activation_req.state
        activation_req.state = to_state
        if serializer.validated_data.get("sandbox_evidence"):
            activation_req.sandbox_evidence = serializer.validated_data["sandbox_evidence"]
        activation_req.notes = notes
        activation_req.save(update_fields=["state", "sandbox_evidence", "notes", "updated_at"])

        # Update provider activation state to mirror
        provider = activation_req.provider
        provider.activation_state = to_state
        update_fields = ["activation_state", "updated_at"]
        if to_state == ActivationState.ACTIVE:
            provider.truth_label = "PPB_API_ACTIVE"  # Only when confirmed active.
            provider.activated_by = request.user
            provider.activated_at = timezone.now()
            update_fields += ["truth_label", "activated_by", "activated_at"]
        elif to_state in {
            ActivationState.SUSPENDED,
            ActivationState.REVOKED,
            ActivationState.DECOMMISSIONED,
            ActivationState.REJECTED,
        }:
            if to_state == ActivationState.SUSPENDED:
                provider.suspended_at = timezone.now()
                update_fields.append("suspended_at")
            if to_state == ActivationState.DECOMMISSIONED:
                provider.decommissioned_at = timezone.now()
                update_fields.append("decommissioned_at")
            provider.truth_label = (
                "DISABLED_IN_PRODUCTION"
                if provider.environment == "PRODUCTION"
                else "ADAPTER_SCAFFOLDED_NOT_CONNECTED"
            )
            update_fields.append("truth_label")
        provider.save(update_fields=update_fields)

        # Immutable decision record
        decision = ProviderActivationDecision.objects.create(
            activation_request=activation_req,
            decided_by=request.user,
            from_state=from_state,
            to_state=to_state,
            decision_notes=notes,
            truth_label=provider.truth_label,
        )

        log_platform_audit(
            action="PROVIDER_ACTIVATION_ADVANCED",
            model_name="ProviderActivationRequest",
            object_id=activation_req.id,
            actor_id=request.user.id,
            metadata={
                "from_state": from_state,
                "to_state": to_state,
                "provider_type": provider.provider_type,
                "truth_label": provider.truth_label,
                "decision_id": str(decision.id),
            },
        )

        return Response(ProviderActivationRequestSerializer(activation_req).data)


class DeadLetterReplayView(ReadOnlyModelViewSet):
    """Platform Owner: manage dead-letter queue replay."""

    permission_classes = [IsAuthenticated, PlatformOwnerRequired]
    serializer_class = IntegrationDeadLetterSerializer
    queryset = IntegrationDeadLetter.objects.select_related("message", "replayed_by").all()

    @action(detail=True, methods=["post"], url_path="replay")
    def replay(self, request, pk=None):
        """Replay a dead-lettered message.

        Idempotent: only replays if not already replayed.
        Requires replay_notes.
        """
        serializer = DeadLetterReplaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        dlq = self.get_object()
        if dlq.replayed_at is not None:
            return Response(
                {"detail": "This dead-letter has already been replayed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dlq.replayed_at = timezone.now()
        dlq.replayed_by = request.user
        dlq.replay_notes = serializer.validated_data["replay_notes"]
        dlq.save(update_fields=["replayed_at", "replayed_by", "replay_notes"])

        # Reset message state for retry pickup
        msg = dlq.message
        msg.state = IntegrationMessage.MessageState.PENDING
        msg.next_retry_at = timezone.now()
        msg.save(update_fields=["state", "next_retry_at"])

        audit_logger = log_audit if msg.tenant_id else log_platform_audit
        audit_logger(
            **({"tenant_id": msg.tenant_id} if msg.tenant_id else {}),
            action="DEAD_LETTER_REPLAYED",
            model_name="IntegrationDeadLetter",
            object_id=dlq.id,
            actor_id=request.user.id,
            metadata={
                "message_id": str(msg.id),
                "message_type": msg.message_type,
                "provider_type": msg.provider.provider_type,
                "replay_notes": serializer.validated_data["replay_notes"],
            },
        )

        return Response(IntegrationDeadLetterSerializer(dlq).data)
