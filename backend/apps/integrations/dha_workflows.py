"""Governed DHA workflows with tenant-bound consent and a durable exchange journal."""
import hashlib
import json
import os
import re
from datetime import timedelta
from urllib.parse import quote

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.core.permissions import require_tenant_capability
from apps.integrations.dha_catalogue import OPERATIONS, SHR_RESOURCES
from apps.integrations.dha_client import DhaClient, DhaError
from apps.integrations.dha_models import DhaConnection, DhaExchange, DhaVisit
from apps.integrations.dha_security import protect, readiness, reveal
from apps.integrations.reliability import compute_backoff_seconds


def authorize(connection, actor, capability):
    require_tenant_capability(actor, connection.tenant_id, capability)
    branches = (actor.metadata or {}).get("branch_ids")
    if branches is not None and not (actor.is_superuser or actor.is_platform_admin) and str(connection.branch_id) not in map(str, branches):
        raise PermissionDenied("The DHA branch is outside your assignment.")


def operational(connection):
    if connection.state != ("ACTIVE" if connection.environment == "PRODUCTION" else "SANDBOX") or not readiness(connection)["ready"]:
        raise ValidationError("This tenant/branch DHA connection is not active and validated.")


def audit(connection, actor, action, object_id, **metadata):
    log_audit(tenant_id=connection.tenant_id, actor_id=actor.pk, action=f"DHA_{action}",
        model_name="DhaConnection", object_id=object_id, metadata={"connection": str(connection.pk), **metadata})


def safe_response(value):
    if isinstance(value, list):
        return [safe_response(v) for v in value]
    if isinstance(value, dict):
        return {k: safe_response(v) for k, v in value.items() if k.lower() not in {
            "access_token", "refresh_token", "consent_token", "token", "otp", "otp_record", "client_secret",
            "authorization_code", "debug_data", "traceback"}}
    return value


def create_visit(connection, actor, patient):
    from apps.patients.models import PatientIdentifier
    authorize(connection, actor, "dha.exchange")
    operational(connection)
    if patient.tenant_id != connection.tenant_id or not patient.is_active or patient.is_deceased:
        raise ValidationError("Select an active patient in this tenant.")
    identifiers = PatientIdentifier.all_objects.filter(patient=patient, tenant_id=connection.tenant_id, verification_status="VERIFIED",
        system__in=["https://cr.kenya-hie.health/fhir/NamingSystem/cr-id", "https://cr.kenya-hie.health"])
    identifiers = [i for i in identifiers if not i.expiry_date or i.expiry_date >= timezone.localdate()]
    if len(identifiers) != 1:
        raise ValidationError("Resolve and verify one Client Registry identifier for this patient first.")
    identifier = identifiers[0]
    cr_id = identifier.value_for_exchange()
    puid = connection.configuration.get("practitioner_map", {}).get(str(actor.pk))
    if not cr_id or not puid:
        raise ValidationError("Verified patient CR and requesting practitioner PUID mappings are required.")
    visit = DhaVisit.all_objects.create(tenant_id=connection.tenant_id, connection=connection, patient=patient, actor=actor)
    visit.protected_context = protect(connection, {"cr_id": cr_id, "practitioner_id": puid})
    visit.save(update_fields=["protected_context"])
    audit(connection, actor, "VISIT_CREATED", visit.pk)
    return visit


def validate_bundle(bundle, context):
    if (bundle.get("resourceType") != "Bundle" or bundle.get("type") != "collection"
            or not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", str(bundle.get("id", "")))
            or not isinstance(bundle.get("entry"), list) or not 1 <= len(bundle["entry"]) <= 100):
        raise ValidationError("Submit an identified FHIR collection Bundle containing at most 100 resources.")
    resources = [row.get("resource", {}) for row in bundle["entry"] if isinstance(row, dict)]
    if len(resources) != len(bundle["entry"]):
        raise ValidationError("Invalid FHIR bundle entries.")
    seen, encounters = set(), set()
    for resource in resources:
        kind, rid = resource.get("resourceType"), resource.get("id")
        if kind not in SHR_RESOURCES or not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", rid) or (kind, rid) in seen:
            raise ValidationError("Each supported resource needs a unique FHIR ID.")
        seen.add((kind, rid))
        if kind == "Encounter":
            refs = {r.get("reference") for r in resource.get("episodeOfCare", []) if isinstance(r, dict)}
            if f"EpisodeOfCare/{context['visit_id']}" not in refs:
                raise ValidationError("The Encounter must reference the consented visit's EpisodeOfCare.")
            encounters.add(f"Encounter/{rid}")
        subject = resource.get("subject", resource.get("patient", {})).get("reference", "")
        if kind != "Medication" and subject != f"Patient/{context['cr_id']}":
            raise ValidationError("Every patient resource must reference the consented CR patient.")
        if kind == "EpisodeOfCare" and rid != context["visit_id"]:
            raise ValidationError("The EpisodeOfCare ID must match the consented visit.")
        if not resource.get("meta", {}).get("security"):
            raise ValidationError("Every shared resource requires reviewed DHA security labels.")
    for resource in resources:
        if resource["resourceType"] not in {"Medication", "Encounter", "EpisodeOfCare"}:
            field = "context" if resource["resourceType"] == "MedicationDispense" else "encounter"
            if resource.get(field, {}).get("reference") not in encounters:
                raise ValidationError("Clinical resources must reference the bundle's Encounter.")
    if not encounters:
        raise ValidationError("A visit-linked Encounter is required.")
    # Typed FHIR structural validation; national bindings are additionally tested in DHA UAT.
    from fhir.resources.bundle import Bundle
    try:
        Bundle.parse_obj(bundle)
    except Exception:
        raise ValidationError("The bundle does not satisfy FHIR structure validation.") from None


def prepare(connection, actor, operation, payload, visit=None, path_values=None):
    op = OPERATIONS.get(operation)
    if not op:
        raise ValidationError("Unknown DHA operation.")
    authorize(connection, actor, op.capability)
    operational(connection)
    if op.claims and not connection.configuration.get("claims_enabled"):
        raise ValidationError("SHA claims workflows are not enabled for this tenant/branch.")
    if not isinstance(payload, dict) or len(json.dumps(payload)) > 1024 * 1024:
        raise ValidationError("Use a bounded JSON object.")
    data = dict(payload)
    context = {}
    values = dict(path_values or {})
    # No identity overrides, even if a browser forges fields in a clinical request.
    if visit:
        if visit.connection_id != connection.pk or visit.tenant_id != connection.tenant_id:
            raise ValidationError("The visit belongs to another connection.")
        context = reveal(connection, visit.protected_context)
        if context.get("practitioner_id") != connection.configuration.get("practitioner_map", {}).get(str(actor.pk)):
            raise PermissionDenied("This visit belongs to a different requesting practitioner.")
        values.update({k: context[k] for k in ("consent_id", "visit_id") if context.get(k)})
    remittance = operation in {"remittances", "remittance_claims"}
    if (op.visit or (op.claims and not remittance)) and not visit:
        raise ValidationError("Select the local DHA visit for this operation.")
    if visit and visit.state in {"CLOSED", "REJECTED"} and operation.startswith(("consent_", "visit_")):
        raise ValidationError("This visit is closed or consent was refused. Start a new consent request for a new visit.")
    reads = {"patient_records", "observations", "bundle_submit"}
    if operation in reads:
        if visit.state != "OPEN" or not context.get("consent_token") or not visit.consent_expires_at or visit.consent_expires_at <= timezone.now():
            raise ValidationError("Active visit consent is required; refresh expired consent first.")
    if operation == "consent_request":
        if visit.state != "PENDING" or context.get("consent_id"):
            raise ValidationError("Consent was already requested; use resend or status.")
        if data.get("visit_type") not in {"OP", "IP"}:
            raise ValidationError("Use OP or IP for the visit type.")
        if data.get("emergency") or data.get("patient_capable") == 0:
            authorize(connection, actor, "dha.emergency")
            if not str(data.get("incapacity_reason", "")).strip():
                raise ValidationError("An incapacity reason is required.")
        if data.get("representative_cr_id") and not data.get("representative_relationship"):
            raise ValidationError("Record the representative relationship.")
        data.update(cr_id=context["cr_id"], practitioner_id=context["practitioner_id"],
            facility_id=connection.configuration["facility_id"], requested_by=actor.get_username())
    if operation == "consent_verify":
        if visit.state not in {"PENDING", "CLOSING"}:
            raise ValidationError("Consent verification is unavailable in this visit state.")
        if data.get("consent_decision") in ("Reject", "0", 0):
            if not data.get("rejection_reason"):
                raise ValidationError("Record why consent was refused.")
        elif not data.get("otp"):
            raise ValidationError("Enter the patient's OTP.")
        data["otp_record"] = context.get("otp_record", "")
    if operation in {"visit_refresh", "visit_close"} and visit.state != "OPEN":
        raise ValidationError("Only an open visit can be refreshed or closed.")
    if operation == "visit_close" and data.get("patient_incapable"):
        authorize(connection, actor, "dha.emergency")
        if not data.get("incapacity_reason"):
            raise ValidationError("An incapacity reason is required.")
    if operation == "patient_records":
        data = {k: v for k, v in data.items() if k in {"resources", "_id", "page_token"}}
        requested = set(str(data.get("resources", "")).split(","))
        if not requested or not requested <= SHR_RESOURCES:
            raise ValidationError("Select supported SHR resources.")
        data.update(cr_id=context["cr_id"], practitioner_id=context["practitioner_id"])
    if operation == "observations":
        data = {k: v for k, v in data.items() if k in {"page_token"}}
        data["subject"] = context["cr_id"]
    if operation == "bundle_submit":
        from apps.integrations.dha_bundles import supply_bundle
        if "supply_id" not in data:
            raise ValidationError("Select a governed medicine supply; arbitrary clinical bundle writes are not accepted.")
        data = supply_bundle(connection, visit, context, data["supply_id"], data.get("security_labels"))
        validate_bundle(data, context)
    if op.claims and not remittance:
        # SHA authorisation tokens are distinct from SHR visit-consent tokens.
        # Identity comes from the local patient visit; tokens never come from the browser.
        for field in ("patient_id", "beneficiary_cr_id", "cr_id"):
            if field in data or field in op.required:
                data[field] = context["cr_id"]
        if operation in {"patient_contacts", "claims_otp", "claims_authorize", "claims_visit"}:
            data["patient_id"] = context["cr_id"]
        data.pop("consent_token", None)
        if context.get("claims_consent_token"):
            data["consent_token"] = context["claims_consent_token"]
        if "consent_token" in op.required and not context.get("claims_consent_token"):
            raise ValidationError("Open or authorise this patient's SHA claim visit first.")
        if operation in {"claim_submit", "claim_add_line", "claim_edit_line", "claim_remove_line", "claim_add_diagnosis", "claim_attachment"} and context.get("claims_phase") in {"SUBMITTED", "CLOSED"}:
            raise ValidationError("This SHA claim is already submitted or closed; use the provider's review/resubmission workflow.")
        if operation in {"eligibility"}:
            data.update(identification_type="CR ID", identification_number=context["cr_id"])
        if op.multipart:
            from apps.integrations.dha_documents import documents_for_exchange
            documents_for_exchange(connection, visit, actor, data.get("documents", []))
            if operation == "claim_attachment" and not data.get("documents"):
                raise ValidationError("Select the stored document to attach.")
        if operation in {"claim_add_line", "claim_edit_line"}:
            from decimal import Decimal, InvalidOperation
            try:
                for field in ("quantity", "unit_price"):
                    if field in data:
                        value = Decimal(str(data[field]))
                        if not value.is_finite() or value < 0 or (field == "quantity" and value == 0):
                            raise ValueError
            except (InvalidOperation, ValueError):
                raise ValidationError("Claim quantities must be positive and prices non-negative finite numbers.") from None
    if operation == "referrals":
        # Restrict queries to referrals addressed to the configured facility.
        data = {k: v for k, v in data.items() if k in {"page_token", "status", "_id"}}
        data["performer:Organization"] = connection.configuration["facility_id"]
    if operation == "open_visits":
        data["facility_id"] = connection.configuration["facility_id"]
    if remittance:
        data = {k: v for k, v in data.items() if k in {"bank_reference", "page", "page_size", "from_date", "to_date"}}
        data.update(facility_id=connection.configuration["facility_id"], facility_id_type="fr-code")
    for facility_field in ("facility_id", "site_code", "facility_fr_code", "fr_code"):
        if facility_field in data:
            data[facility_field] = connection.configuration["facility_id"]
    for type_field in ("facility_id_type", "site_code_type"):
        if type_field in data:
            data[type_field] = "fr-code"
    if operation.startswith("callback_"):
        authorize(connection, actor, "dha.configure")
        if not (actor.is_platform_admin or actor.is_superuser):
            raise PermissionDenied("Platform approval is required for callback registration.")
        values.update(hie_tenant_id=connection.configuration.get("hie_tenant_id", ""), facility_id=connection.configuration["facility_id"])
        if operation == "callback_register":
            entity = data.get("entity_type")
            base = os.environ.get("TIBATRACE_DHA_CALLBACK_BASE_URL", "").rstrip("/")
            from urllib.parse import urlsplit
            target = urlsplit(base)
            if entity not in {"claim", "preauth", "authorization"} or target.scheme != "https" or not target.hostname or target.query or target.fragment or target.username:
                raise ValidationError("Configure a public HTTPS callback base URL and choose a supported entity type.")
            ref = connection.configuration.get("callback_hie_secret_ref")
            if not ref:
                raise ValidationError("Arrange a bearer callback secret reference with DHA first.")
            data = {"name": f"TibaTrace {entity}", "entity_type": entity, "base_url": base,
                "auth_type": "bearer", "secret_ref": ref, "facility_fr_code": connection.configuration["facility_id"],
                "environment": connection.environment.lower(), "tenant_code": connection.configuration.get("hie_tenant_id", "")}
        if operation == "callback_operation":
            entity = data.get("entity_type")
            registered = False
            for previous in DhaExchange.all_objects.filter(connection=connection, operation="callback_register", state="ACCEPTED"):
                body = reveal(connection, previous.protected_response)
                original = reveal(connection, previous.protected_request)["payload"]
                if body.get("endpoint_id") == values.get("endpoint_id") and original.get("entity_type") == entity:
                    registered = True
                    break
            if not registered:
                raise ValidationError("Register this entity's callback endpoint on this connection first.")
            data = {"name": f"TibaTrace {entity} status", "action": "status_changed", "method": "POST",
                "path": f"/api/nif/dha/callbacks/{connection.pk}/{entity}/"}
    for required in op.required:
        if not data.get(required):
            raise ValidationError(f"{required} is required for {operation}.")
    path = op.path or connection.configuration.get("remittance_paths", {}).get(operation)
    if not path:
        raise ValidationError("DHA must confirm this remittance contract path before activation of this operation.")
    for name in re.findall(r"{(\w+)}", path):
        value = values.get(name)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,120}", value):
            raise ValidationError(f"A valid {name} is required.")
        path = path.replace("{" + name + "}", quote(value, safe=""))
    return op, path, data, context


@transaction.atomic
def enqueue(connection, actor, operation, payload, key, visit=None, path_values=None):
    # Serialize command keys and consent transitions for this branch connection.
    connection = DhaConnection.all_objects.select_for_update().get(pk=connection.pk, tenant_id=connection.tenant_id)
    fingerprint = hashlib.sha256(json.dumps({"operation": operation, "payload": payload,
        "visit": str(visit.pk) if visit else None, "path": path_values or {}}, sort_keys=True).encode()).hexdigest()
    existing = DhaExchange.all_objects.filter(connection=connection, idempotency_key=key).first()
    if existing:
        authorize(connection, actor, OPERATIONS[existing.operation].capability)
        if existing.fingerprint != fingerprint or existing.actor_id != actor.pk:
            raise ValidationError("This DHA retry key belongs to another command.")
        return existing
    if visit:
        visit.refresh_from_db()
        if OPERATIONS[operation].method != "GET" and operation != "visit_refresh" and DhaExchange.all_objects.filter(visit=visit, state__in=["PENDING", "IN_FLIGHT", "RETRY", "UNCERTAIN"]).exists():
            raise ValidationError("Reconcile the outstanding command for this visit first.")
    prepare(connection, actor, operation, payload, visit, path_values)
    exchange = DhaExchange.all_objects.create(tenant_id=connection.tenant_id, connection=connection, actor=actor,
        visit=visit, operation=operation, idempotency_key=key, fingerprint=fingerprint,
        connection_revision=connection.revision,
        protected_request=protect(connection, {"payload": payload, "path_values": path_values or {}}))
    audit(connection, actor, "QUEUED", exchange.pk, operation=operation)
    return exchange


def update_visit(exchange, response):
    visit = exchange.visit
    if not visit or not isinstance(response, dict):
        return
    context = reveal(exchange.connection, visit.protected_context)
    op = exchange.operation
    if op in {"claims_authorize", "claims_visit"}:
        token = response.get("consent_token") or response.get("token")
        if token:
            context["claims_consent_token"] = token
            context["claims_phase"] = "OPEN"
        if response.get("guid"):
            context["claims_guid"] = response["guid"]
        visit.protected_context = protect(exchange.connection, context)
        visit.save(update_fields=["protected_context", "updated_at"])
        return
    if op in {"claim_submit", "claim_close", "claim_discharge"}:
        context["claims_phase"] = "CLOSED" if op == "claim_close" else "SUBMITTED"
        visit.protected_context = protect(exchange.connection, context)
        visit.save(update_fields=["protected_context", "updated_at"])
        return
    if not op.startswith(("consent_", "visit_")):
        return
    if response.get("end_date"):
        visit.state = "CLOSED"
        context.pop("consent_token", None)
    elif str(response.get("consent_status", "")).lower() in {"rejected", "revoked", "expired"}:
        visit.state = "REJECTED"
        context.pop("consent_token", None)
    elif op == "visit_close":
        if not response.get("otp_record"):
            raise DhaError("INVALID_CLOSE_RESPONSE", uncertain=True)
        visit.state = "CLOSING"
        context.pop("consent_token", None)
    elif response.get("consent_token"):
        if not response.get("visit_id", context.get("visit_id")):
            raise DhaError("INVALID_CONSENT_RESPONSE", uncertain=True)
        visit.state = "OPEN"
        # A bounded local cache lifetime; DHA remains authoritative on every access.
        visit.consent_expires_at = timezone.now() + timedelta(minutes=5)
    for key in ("consent_id", "visit_id", "otp_record", "consent_token"):
        if response.get(key):
            context[key] = response[key]
    if visit.state in {"CLOSED", "REJECTED", "CLOSING"}:
        context.pop("consent_token", None)
    visit.protected_context = protect(exchange.connection, context)
    visit.save(update_fields=["state", "consent_expires_at", "protected_context", "updated_at"])


def validate_response(operation, payload, response):
    """A 2xx with an unusable acknowledgement cannot establish workflow success."""
    if operation == "bundle_submit" and (not isinstance(response, dict) or response.get("mediator_id") != payload["id"]):
        raise DhaError("BUNDLE_ACKNOWLEDGEMENT_MISMATCH", uncertain=True)
    if operation == "consent_request" and (not isinstance(response, dict) or not (
            (response.get("consent_id") and response.get("otp_record")) or (response.get("visit_id") and response.get("consent_token")))):
        raise DhaError("INVALID_CONSENT_RESPONSE", uncertain=True)
    if operation == "consent_verify" and (not isinstance(response, dict) or not (
            response.get("end_date") or response.get("consent_status") or (response.get("visit_id") and response.get("consent_token")))):
        raise DhaError("INVALID_CONSENT_RESPONSE", uncertain=True)
    if operation in {"patient_records", "observations", "referrals"} and (
            not isinstance(response, dict) or response.get("resourceType") != "Bundle" or response.get("type") != "searchset"):
        raise DhaError("INVALID_FHIR_SEARCH_RESPONSE")


def resource_preserved(expected, actual):
    """Compare typed FHIR values, allowing server metadata and added object fields."""
    from fhir.resources import get_fhir_model_class
    try:
        model = get_fhir_model_class(expected["resourceType"])
        expected = model.parse_obj(expected).dict(exclude_none=True)
        actual = model.parse_obj(actual).dict(exclude_none=True)
    except Exception:
        return False
    labels = expected.get("meta", {}).get("security", [])
    actual_labels = actual.get("meta", {}).get("security", [])
    if any(label not in actual_labels for label in labels):
        return False
    def contains(want, got):
        if isinstance(want, dict):
            return isinstance(got, dict) and all(k in got and contains(v, got[k]) for k, v in want.items())
        if isinstance(want, list):
            return isinstance(got, list) and len(want) == len(got) and all(contains(a, b) for a, b in zip(want, got))
        return want == got
    return contains({k: v for k, v in expected.items() if k != "meta"}, actual)


def execute(exchange):
    with transaction.atomic():
        # Lock the exchange itself: visit is nullable and PostgreSQL cannot
        # lock the nullable side of its outer join.
        exchange = DhaExchange.all_objects.select_for_update(of=("self",)).select_related("connection__tenant", "connection__branch", "actor", "visit").get(pk=exchange.pk)
        if exchange.state not in {"PENDING", "RETRY"}:
            return exchange
        if exchange.next_attempt_at and exchange.next_attempt_at > timezone.now():
            return exchange
        exchange.state = "IN_FLIGHT"
        exchange.attempts += 1
        exchange.lease_expires_at = timezone.now() + timedelta(seconds=90)
        exchange.save(update_fields=["state", "attempts", "lease_expires_at", "updated_at"])
    try:
        exchange.connection.refresh_from_db()
        if exchange.connection_revision != exchange.connection.revision:
            raise ValidationError("DHA configuration changed; review the command.")
        request = reveal(exchange.connection, exchange.protected_request)
        op, path, payload, context = prepare(exchange.connection, exchange.actor, exchange.operation,
            request["payload"], exchange.visit, request["path_values"])
        if op.method != "GET" and request.get("resolved_payload"):
            # A retry transmits the original prepared command, never a newly
            # recomputed clinical snapshot under the same request identity.
            payload = request["resolved_payload"]
        request["resolved_payload"] = payload
        exchange.protected_request = protect(exchange.connection, request)
        DhaExchange.all_objects.filter(pk=exchange.pk, tenant_id=exchange.tenant_id).update(protected_request=exchange.protected_request)
        files = None
        if op.multipart:
            from apps.integrations.dha_documents import documents_for_exchange
            payload = dict(payload)
            files = documents_for_exchange(exchange.connection, exchange.visit, exchange.actor, payload.pop("documents", []), read=True)
        response, status = DhaClient(exchange.connection).call(op, path, payload,
            consent_token=context.get("consent_token", ""), practitioner_id=context.get("practitioner_id", ""), files=files)
        validate_response(exchange.operation, payload, response)
        for field in ("payload", "resolved_payload"):
            request.get(field, {}).pop("otp", None)
        exchange.protected_request = protect(exchange.connection, request)
        with transaction.atomic():
            update_visit(exchange, response)
            exchange.protected_response = protect(exchange.connection, response)
            exchange.http_status = status
            exchange.state = "CONFIRMED" if op.method == "GET" else "ACCEPTED"
            exchange.error_code = ""
            exchange.save(update_fields=["protected_request", "protected_response", "http_status", "state", "error_code", "updated_at"])
    except DhaError as exc:
        exchange.http_status, exchange.error_code = exc.status, exc.code
        exchange.state = "UNCERTAIN" if exc.uncertain else "RETRY" if exc.retryable and exchange.attempts < 5 else "FAILED"
        if exchange.state == "RETRY":
            exchange.next_attempt_at = timezone.now() + timedelta(seconds=compute_backoff_seconds(exchange.attempts))
    except (ValidationError, PermissionDenied):
        exchange.state, exchange.error_code = "FAILED", "CONFIGURATION_OR_AUTHORITY_CHANGED"
    finally:
        # OTPs are transient even inside the encrypted journal; never retry a consumed OTP.
        request = reveal(exchange.connection, exchange.protected_request)
        if any("otp" in request.get(field, {}) for field in ("payload", "resolved_payload")):
            for field in ("payload", "resolved_payload"):
                request.get(field, {}).pop("otp", None)
            exchange.protected_request = protect(exchange.connection, request)
            if exchange.state == "RETRY":
                exchange.state = "FAILED"
        exchange.lease_expires_at = None
        exchange.save()
    audit(exchange.connection, exchange.actor, "EXECUTED", exchange.pk, operation=exchange.operation,
        state=exchange.state, error_code=exchange.error_code)
    return exchange
