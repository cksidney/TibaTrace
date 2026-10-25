"""Tenant-scoped DHA setup, consent, exchange, reconciliation and callback APIs."""
import hashlib
import hmac
import json
import uuid

from django.core.exceptions import PermissionDenied as DomainDenied
from django.core.exceptions import ValidationError as DomainError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import include, path
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiTypes, extend_schema, inline_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter
from rest_framework.views import APIView

from apps.integrations.dha_catalogue import OPERATIONS
from apps.integrations.dha_client import DhaClient, DhaError
from apps.integrations.dha_models import DhaCallback, DhaConnection, DhaExchange, DhaVisit
from apps.integrations.dha_security import protect, readiness, reveal, secret, validate_config
from apps.integrations.dha_workflows import (
    audit,
    authorize,
    create_visit,
    enqueue,
    execute,
    operational,
    resource_preserved,
    safe_response,
)
from apps.organizations.models import Location
from apps.patients.models import Patient


def domain(call):
    try:
        return call()
    except DomainError as exc:
        raise ValidationError(exc.messages) from None
    except DomainDenied:
        raise PermissionDenied("The required DHA authority or branch assignment is missing.") from None
    except DhaError as exc:
        return Response({"detail": exc.code}, status=502)


def local_uuid(value):
    return serializers.UUIDField().run_validation(value)


class ConnectionSerializer(serializers.ModelSerializer):
    readiness = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = DhaConnection
        fields = ("id", "branch", "branch_name", "environment", "state", "configuration", "revision",
            "validated_revision", "validated_at", "approved_at", "readiness")
        read_only_fields = ("state", "revision", "validated_revision", "validated_at", "approved_at")
        extra_kwargs = {"branch": {"read_only": True}}

    def get_readiness(self, obj) -> dict:
        return readiness(obj)

    def validate_configuration(self, value):
        domain(lambda: validate_config(value))
        tenant_id = getattr(self.context["request"], "tenant_id", None) or self.context["request"].user.tenant_id
        from apps.identity.models import User
        from apps.medicines.models import CommercialSKU
        from apps.practitioners.models import Practitioner
        for field, model in (("practitioner_map", User), ("prescriber_map", Practitioner), ("product_map", CommercialSKU)):
            ids = list(value.get(field, {})) if field == "practitioner_map" else list(value.get(field, {}).values())
            manager = getattr(model, "all_objects", model.objects)
            if ids and manager.filter(tenant_id=tenant_id, pk__in=ids).count() != len(set(ids)):
                raise ValidationError(f"{field} contains records outside the selected tenant.")
        return value


def visit_data(visit):
    return {"id": str(visit.pk), "patient": str(visit.patient_id), "patient_name": visit.patient.full_name, "state": visit.state,
        "consent_expires_at": visit.consent_expires_at, "created_at": visit.created_at}


def exchange_data(row, include_response=False):
    data = {"id": str(row.pk), "operation": row.operation, "visit": str(row.visit_id) if row.visit_id else None,
        "state": row.state, "attempts": row.attempts, "http_status": row.http_status,
        "error_code": row.error_code, "next_attempt_at": row.next_attempt_at, "created_at": row.created_at}
    if include_response and row.protected_response:
        data["response"] = safe_response(reveal(row.connection, row.protected_response))
    return data


class CommandSerializer(serializers.Serializer):
    operation = serializers.ChoiceField(choices=tuple(OPERATIONS))
    payload = serializers.JSONField(default=dict)
    idempotency_key = serializers.CharField(max_length=100, min_length=8)
    visit = serializers.UUIDField(required=False)
    path_values = serializers.DictField(child=serializers.CharField(max_length=120), default=dict)


class DhaConnectionViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ConnectionSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method in {"POST", "PATCH"} and not isinstance(request.data, dict):
            raise ValidationError("Use a JSON object for this DHA command.")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DhaConnection.objects.none()
        tenant_id = getattr(self.request, "tenant_id", None) or self.request.user.tenant_id
        qs = DhaConnection.objects.for_tenant(tenant_id).select_related("branch", "tenant") if tenant_id else DhaConnection.objects.none()
        branches = (self.request.user.metadata or {}).get("branch_ids")
        if branches is not None and not (self.request.user.is_platform_admin or self.request.user.is_superuser):
            qs = qs.filter(branch_id__in=branches)
        return qs

    def connection(self, capability="dha.configure"):
        connection = self.get_object()
        domain(lambda: authorize(connection, self.request.user, capability))
        return connection

    def list(self, request):
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        if not tenant_id or not request.user.has_capability("dha.configure", tenant_id=tenant_id):
            raise PermissionDenied("DHA configuration authority is required.")
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.connection()).data)

    @extend_schema(request=inline_serializer(name="DhaConnectionCreate", fields={
        "branch": serializers.UUIDField(), "environment": serializers.ChoiceField(choices=["SANDBOX", "PRODUCTION"]),
        "configuration": serializers.DictField()}), responses={201: ConnectionSerializer})
    def create(self, request):
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        branch = get_object_or_404(Location.all_objects, pk=local_uuid(request.data.get("branch")), tenant_id=tenant_id)
        connection = DhaConnection(tenant_id=tenant_id, branch=branch)
        domain(lambda: authorize(connection, request.user, "dha.configure"))
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if DhaConnection.all_objects.filter(tenant_id=tenant_id, branch=branch, environment=serializer.validated_data["environment"]).exists():
            raise ValidationError("This branch already has a connection in that environment.")
        with transaction.atomic():
            connection = serializer.save(tenant_id=tenant_id, branch=branch)
            audit(connection, request.user, "CONFIGURED", connection.pk)
        return Response(self.get_serializer(connection).data, status=201)

    def partial_update(self, request, pk=None):
        connection = self.connection()
        if "environment" in request.data or "branch" in request.data:
            raise ValidationError("Create a separate connection for a different branch or environment.")
        serializer = self.get_serializer(connection, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            connection = DhaConnection.all_objects.select_for_update().get(pk=connection.pk, tenant_id=connection.tenant_id)
            if "configuration" in serializer.validated_data:
                connection.configuration = serializer.validated_data["configuration"]
                connection.revision += 1
                connection.state = "DISABLED"
                connection.approved_at = None
                connection.approved_by = None
                connection.approval_evidence = {}
                connection.save()
                audit(connection, request.user, "CONFIGURATION_CHANGED", connection.pk, revision=connection.revision)
        return Response(self.get_serializer(connection).data)

    @action(detail=True, methods=["post"])
    @extend_schema(request=None, responses=ConnectionSerializer)
    def probe(self, request, pk=None):
        connection = self.connection()
        self.require_owner(request)
        def run():
            check = readiness(connection)
            blockers = [b for b in check["blockers"] if not b.startswith("Validate connectivity")]
            if blockers:
                raise DomainError(blockers)
            body, _ = DhaClient(connection).call(OPERATIONS["facility_search"], "/facilities/search",
                {"identifier": connection.configuration["facility_id"], "identifier-type": "fr-code"})
            if not isinstance(body, dict) or connection.configuration["facility_id"] not in {body.get("frCode"), body.get("fidCode")}:
                raise DomainError("DHA did not confirm the configured facility identifier.")
            DhaConnection.all_objects.filter(pk=connection.pk, tenant_id=connection.tenant_id, revision=connection.revision).update(
                validated_revision=connection.revision, validated_at=timezone.now())
            connection.refresh_from_db()
            audit(connection, request.user, "CONNECTIVITY_VALIDATED", connection.pk, revision=connection.revision)
            return Response(self.get_serializer(connection).data)
        return domain(run)

    @staticmethod
    def require_owner(request):
        if not (request.user.is_platform_admin or request.user.is_superuser):
            raise PermissionDenied("Platform Owner approval is required for DHA activation.")

    @action(detail=True, methods=["post"])
    @extend_schema(request=inline_serializer(name="DhaActivationEvidence", fields={
        "evidence": serializers.DictField(child=serializers.CharField())}), responses=ConnectionSerializer)
    def activate(self, request, pk=None):
        connection = self.connection()
        self.require_owner(request)
        evidence = request.data.get("evidence", {})
        fields = ("sandbox_uat", "security_review", "system_dpia", "facility_approval")
        if connection.environment == "PRODUCTION":
            fields += ("dha_approval", "production_access")
        if not isinstance(evidence, dict) or any(not isinstance(evidence.get(k), str) or not 5 <= len(evidence[k]) <= 250 for k in fields):
            raise ValidationError("Provide evidence references for: " + ", ".join(fields))
        with transaction.atomic():
            connection = DhaConnection.all_objects.select_for_update().select_related("tenant", "branch").get(pk=connection.pk, tenant_id=connection.tenant_id)
            check = readiness(connection)
            if not check["ready"]:
                raise ValidationError(check["blockers"])
            connection.state = "ACTIVE" if connection.environment == "PRODUCTION" else "SANDBOX"
            connection.approval_evidence = {k: evidence[k] for k in fields}
            connection.approved_by, connection.approved_at = request.user, timezone.now()
            connection.save()
            audit(connection, request.user, "ACTIVATED", connection.pk, revision=connection.revision, environment=connection.environment)
        return Response(self.get_serializer(connection).data)

    @action(detail=True, methods=["post"])
    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def suspend(self, request, pk=None):
        connection = self.connection()
        with transaction.atomic():
            DhaConnection.all_objects.filter(pk=connection.pk, tenant_id=connection.tenant_id).update(state="SUSPENDED")
            audit(connection, request.user, "SUSPENDED", connection.pk)
        return Response({"state": "SUSPENDED"})

    @action(detail=True, methods=["get"])
    @extend_schema(responses={200: {"type": "array", "items": {"type": "object"}}})
    def catalogue(self, request, pk=None):
        connection = self.connection()
        return Response([{ "code": code, "method": op.method, "path": op.path or connection.configuration.get("remittance_paths", {}).get(code, ""),
            "contract_bound": bool(op.path or connection.configuration.get("remittance_paths", {}).get(code)), "capability": op.capability,
            "requires_visit": op.visit or (op.claims and code not in {"remittances", "remittance_claims"}),
            "claims": op.claims, "required": op.required} for code, op in OPERATIONS.items()])

    @action(detail=True, methods=["get", "post"])
    @extend_schema(methods=["POST"], request=inline_serializer(name="DhaVisitCreate", fields={
        "patient": serializers.UUIDField()}), responses={201: OpenApiTypes.OBJECT})
    @extend_schema(methods=["GET"], responses={200: {"type": "array", "items": {"type": "object"}}})
    def visits(self, request, pk=None):
        connection = self.connection("dha.exchange")
        if request.method == "GET":
            return Response([visit_data(v) for v in connection.visits.filter(actor=request.user).select_related("patient").order_by("-created_at")[:100]])
        patient = get_object_or_404(Patient.all_objects, tenant_id=connection.tenant_id, pk=local_uuid(request.data.get("patient")))
        return domain(lambda: Response(visit_data(create_visit(connection, request.user, patient)), status=201))

    @action(detail=True, methods=["post"], url_path="commands")
    @extend_schema(request=CommandSerializer, responses={200: OpenApiTypes.OBJECT, 202: OpenApiTypes.OBJECT})
    def commands(self, request, pk=None):
        connection = self.get_object()
        serializer = CommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        visit = get_object_or_404(DhaVisit.all_objects, connection=connection, pk=data["visit"]) if data.get("visit") else None
        def run():
            row = enqueue(connection, request.user, data["operation"], data["payload"], data["idempotency_key"], visit, data["path_values"])
            row = execute(row)
            result = exchange_data(row, include_response=True)
            if row.visit_id:
                row.visit.refresh_from_db()
                result["visit_state"] = row.visit.state
            return Response(result, status=202 if row.state in {"PENDING", "RETRY", "IN_FLIGHT", "ACCEPTED", "UNCERTAIN"} else 200)
        return domain(run)

    @action(detail=True, methods=["get"])
    @extend_schema(responses={200: {"type": "array", "items": {"type": "object"}}})
    def exchanges(self, request, pk=None):
        connection = self.connection()
        return Response([exchange_data(row) for row in connection.exchanges.order_by("-created_at")[:100]])

    @action(detail=True, methods=["get"])
    @extend_schema(responses={200: {"type": "array", "items": {"type": "object"}}})
    def callbacks(self, request, pk=None):
        connection = self.connection("dha.claims")
        return Response([{"id": str(row.pk), "entity_type": row.entity_type, "state": row.state,
            "created_at": row.created_at, "notification": safe_response(reveal(connection, row.protected_payload))}
            for row in DhaCallback.all_objects.filter(connection=connection).order_by("-created_at")[:100]])

    @action(detail=True, methods=["post"], url_path="resolve-uncertain")
    @extend_schema(request=inline_serializer(name="DhaUncertainResolution", fields={
        "exchange": serializers.UUIDField(), "outcome": serializers.ChoiceField(choices=["RECEIVED", "NOT_RECEIVED"]),
        "evidence_reference": serializers.CharField(min_length=10, max_length=250)}), responses=OpenApiTypes.OBJECT)
    def resolve_uncertain(self, request, pk=None):
        connection = self.connection()
        self.require_owner(request)
        evidence = request.data.get("evidence_reference", "")
        outcome = request.data.get("outcome")
        if not isinstance(evidence, str) or not 10 <= len(evidence) <= 250 or outcome not in {"NOT_RECEIVED", "RECEIVED"}:
            raise ValidationError("Record provider-verified evidence and a RECEIVED or NOT_RECEIVED outcome.")
        with transaction.atomic():
            row = get_object_or_404(DhaExchange.all_objects.select_for_update(), pk=local_uuid(request.data.get("exchange")),
                connection=connection, state="UNCERTAIN")
            # This records the operator's investigation, not a clinical or payer approval.
            row.state = "FAILED" if outcome == "NOT_RECEIVED" else "ACCEPTED"
            row.error_code = "MANUALLY_RECONCILED"
            row.save(update_fields=["state", "error_code", "updated_at"])
            audit(connection, request.user, "UNCERTAIN_RECONCILED", row.pk, outcome=outcome, evidence_reference=evidence)
        return Response(exchange_data(row))

    @action(detail=True, methods=["post"], url_path="confirm-bundle")
    @extend_schema(request=inline_serializer(name="DhaBundleConfirmation", fields={"exchange": serializers.UUIDField(),
        "visit": serializers.UUIDField(required=False)}), responses={200: OpenApiTypes.OBJECT, 202: OpenApiTypes.OBJECT})
    def confirm_bundle(self, request, pk=None):
        connection = self.connection("dha.exchange")
        submitted = get_object_or_404(DhaExchange.all_objects, connection=connection,
            pk=local_uuid(request.data.get("exchange")), operation="bundle_submit", state__in=["ACCEPTED", "UNCERTAIN", "CONFIRMED"])
        consent_visit = (get_object_or_404(DhaVisit.all_objects, connection=connection, pk=local_uuid(request.data["visit"]), patient_id=submitted.visit.patient_id)
            if request.data.get("visit") else submitted.visit)
        def run():
            original = reveal(connection, submitted.protected_request).get("resolved_payload")
            if not original or "entry" not in original:
                raise DomainError("The submission has no transmitted bundle to reconcile.")
            # Confirm every resource by ID and content; existence alone is insufficient for a correction.
            for entry in original["entry"]:
                resource = entry["resource"]
                op = "patient_records"
                row = enqueue(connection, request.user, op, {"resources": resource["resourceType"], "_id": resource["id"]},
                    f"confirm-{submitted.pk}-{uuid.uuid4()}", consent_visit)
                row = execute(row)
                if row.state != "CONFIRMED":
                    return Response({"state": "AWAITING_CONFIRMATION", "exchange": exchange_data(row)}, status=202)
                body = reveal(connection, row.protected_response)
                actual = [e.get("resource", {}) for e in body.get("entry", [])]
                if not any(r.get("resourceType") == resource["resourceType"] and r.get("id") == resource["id"]
                        and resource_preserved(resource, r) for r in actual):
                    return Response({"state": "AWAITING_CONFIRMATION"}, status=202)
            submitted.state = "CONFIRMED"
            submitted.save(update_fields=["state", "updated_at"])
            audit(connection, request.user, "BUNDLE_CONFIRMED", submitted.pk)
            return Response(exchange_data(submitted))
        return domain(run)


class DhaCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, auth=[])
    def post(self, request, connection_id, entity_type):
        connection = get_object_or_404(DhaConnection.all_objects.select_related("tenant", "branch"), pk=connection_id)
        def run():
            expected = secret(connection.configuration.get("callback_secret_ref"))
            if len(expected) < 32 or not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + expected):
                raise PermissionDenied("Invalid DHA callback authentication.")
            operational(connection)
            if len(request.body) > 65536:
                raise ValidationError("Callback payload too large.")
            body = request.data
            if not isinstance(body, dict):
                raise ValidationError("Use a JSON callback object.")
            required = ("subject_guid", "from_state", "to_state", "timestamp", "facility_fr_code")
            if (entity_type not in {"claim", "preauth", "authorization"} or body.get("entity_type") != entity_type
                    or any(not isinstance(body.get(k), str) or not body[k] or len(body[k]) > 160 for k in required)
                    or body["facility_fr_code"] != connection.configuration["facility_id"]):
                raise ValidationError("The callback entity or facility context is invalid.")
            try:
                stamp = parse_datetime(body["timestamp"])
            except (ValueError, TypeError):
                stamp = None
            if not stamp or timezone.is_naive(stamp) or stamp > timezone.now() + timezone.timedelta(minutes=5):
                raise ValidationError("The callback timestamp is invalid.")
            if body.get("tenant_code") and body["tenant_code"] != connection.configuration.get("hie_tenant_id"):
                raise ValidationError("The callback tenant context is invalid.")
            body = {k: v for k, v in body.items() if k in {"subject_guid", "provider_claim_no", "from_state", "to_state",
                "facility_fr_code", "entity_type", "timestamp", "consent_token", "notes", "tenant_code", "authorization_reason"}}
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            _, created = DhaCallback.all_objects.get_or_create(connection=connection, digest=digest,
                defaults={"tenant_id": connection.tenant_id, "entity_type": entity_type, "protected_payload": protect(connection, body)})
            if created:
                from apps.audit.service import log_audit
                log_audit(tenant_id=connection.tenant_id, action="DHA_CALLBACK_RECEIVED", model_name="DhaCallback",
                    object_id=connection.pk, metadata={"entity_type": entity_type, "digest": digest})
            return Response({"received": True, "duplicate": not created})
        return domain(run)


router = SimpleRouter()
router.register("connections", DhaConnectionViewSet, basename="dha-connection")
urlpatterns = [path("", include(router.urls)),
    path("callbacks/<uuid:connection_id>/<str:entity_type>/", DhaCallbackView.as_view(), name="dha-callback")]
