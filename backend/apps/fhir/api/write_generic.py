import hashlib
import importlib
import json
import logging
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.response import Response

from apps.audit.service import log_audit
from apps.core.tenant_context import get_current_tenant_id
from apps.fhir.api.base import BaseFHIRAPIView
from apps.fhir.api.permissions import FHIRResourcePermission
from apps.fhir.exceptions import (
    FHIRIdempotencyError,
    FHIRNotSupportedError,
    FHIRSecurityError,
    FHIRValidationError,
)
from apps.fhir.models import FHIRIdempotencyRecord
from apps.fhir.services.resource_registry import FHIRResourceRegistry
from apps.workflows.service import emit_event

logger = logging.getLogger(__name__)

class FHIRWriteView(BaseFHIRAPIView):
    """Generic view to handle supported FHIR create and update operations."""

    permission_classes = [FHIRResourcePermission]

    def post(self, request, *args, **kwargs):
        return self._write(request, operation="create", resource_id=kwargs.get("id"))

    def put(self, request, *args, **kwargs):
        return self._write(request, operation="update", resource_id=kwargs.get("id"))

    def _write(self, request, *, operation: str, resource_id=None):
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            raise FHIRSecurityError("Missing tenant context.")
        if not settings.FHIR_WRITE_INTERACTIONS_ENABLED:
            raise FHIRNotSupportedError(
                "FHIR writes are disabled until the production certification gate passes.",
                code="not-supported",
            )

        resource_type = self.fhir_resource_type
        registration = FHIRResourceRegistry.get_registration(resource_type)
        user_tenant_id = getattr(request.user, "tenant_id", None)
        if user_tenant_id and str(user_tenant_id) != str(tenant_id):
            raise FHIRSecurityError("Authenticated user is outside the active tenant.", code="forbidden")

        interaction_supported = (
            registration.interactions.create
            if operation == "create"
            else registration.interactions.update
        )
        if not interaction_supported:
            raise FHIRNotSupportedError(
                f"{operation.title()} operation not supported for {resource_type}"
            )
        if operation == "update" and not resource_id:
            raise FHIRValidationError("Update requires a resource id in the URL.")

        # Parse and validate the FHIR resource using fhir.resources (Pydantic v1)
        payload = request.data.copy()
        if payload.get("resourceType") != resource_type:
            raise FHIRValidationError(
                message=f"Expected resourceType {resource_type}",
                diagnostics=f"Received {payload.get('resourceType')}"
            )
        if resource_id:
            payload_id = payload.get("id")
            if payload_id and str(payload_id) != str(resource_id):
                raise FHIRValidationError(
                    "Resource id does not match the request URL.",
                    expression="id",
                )
            payload["id"] = str(resource_id)
        idempotency_key = str(
            getattr(request, "headers", {}).get("Idempotency-Key")
            or getattr(request, "headers", {}).get("X-Idempotency-Key")
            or ""
        ).strip()
        if len(idempotency_key) > 255:
            raise FHIRValidationError("Idempotency-Key cannot exceed 255 characters.")
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "operation": operation,
                    "resource_type": resource_type,
                    "resource_id": str(resource_id or ""),
                    "payload": payload,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

        try:
            # Dynamically import and parse the resource model
            resource_module = importlib.import_module(f"fhir.resources.{resource_type.lower()}")
            resource_class = getattr(resource_module, resource_type)
            fhir_instance = resource_class.parse_obj(payload)
        except Exception as exc:
            logger.warning(
                "FHIR resource parsing failed for %s; exception_type=%s",
                resource_type,
                type(exc).__name__,
            )
            raise FHIRValidationError(
                message="Resource validation failed.",
                diagnostics="Payload does not conform to the declared FHIR R4 resource schema.",
            )

        converter = registration.converter_class()

        # Convert FHIR resource to Domain Command
        context = {"tenant_id": tenant_id, "user": request.user}
        conversion_result = converter.to_domain_command(fhir_instance, context)

        if conversion_result.errors:
            # We raise the first error as a validation error for simplicity
            raise FHIRValidationError(
                message="Failed to map to domain command.",
                diagnostics="; ".join(conversion_result.errors)
            )

        domain_command = conversion_result.domain_command

        if not domain_command:
            # If the converter is stubbed
            return Response(status=501, data={"status": "Not Implemented", "warnings": conversion_result.warnings})

        # --- Phase 5.5 Linkage: Inline CDS Execution ---
        if resource_type == "MedicationRequest":
            cds_outcome = self._evaluate_cds_for_medication_request(domain_command, fhir_instance)
            if cds_outcome:
                # If there's a blocking alert, we raise 422 Unprocessable Entity with OperationOutcome
                # For non-blocking, we could append it to the response.
                if any(issue.severity in ("fatal", "error") for issue in cds_outcome.issue):
                    return Response(cds_outcome.dict(exclude_none=True), status=422)

        processor = getattr(registration.service_class, "process_domain_command", None)
        if not callable(processor):
            raise FHIRNotSupportedError(
                f"{operation.title()} operation is not implemented for {resource_type}.",
                code="not-supported",
            )

        existed_before = bool(
            resource_id
            and registration.service_class.get_by_id(str(resource_id), tenant_id)
        )

        with transaction.atomic():
            idempotency_record = None
            if idempotency_key:
                idempotency_record, replay = self._claim_idempotency(
                    tenant_id=tenant_id,
                    key=idempotency_key,
                    request_hash=request_hash,
                    resource_type=resource_type,
                    operation=operation,
                    actor_id=getattr(request.user, "id", None),
                )
                if replay:
                    existing = registration.service_class.get_by_id(
                        str(idempotency_record.resource_id),
                        tenant_id,
                    )
                    if not existing:
                        raise FHIRIdempotencyError(
                            "The idempotent result is no longer available in the active tenant."
                        )
                    replay_rendered = converter.to_fhir(existing, {"tenant_id": tenant_id})
                    if replay_rendered.errors or not replay_rendered.fhir_resource:
                        raise FHIRValidationError("The idempotent result could not be rendered as FHIR.")
                    replay_response = Response(
                        replay_rendered.fhir_resource.dict(exclude_none=True),
                        status=idempotency_record.response_status or status.HTTP_200_OK,
                    )
                    replay_response["Location"] = request.build_absolute_uri(
                        f"/api/fhir/r4/{resource_type}/{existing.id}"
                    )
                    replay_response["X-Idempotent-Replay"] = "true"
                    return replay_response

            domain_instance = processor(
                domain_command,
                {
                    "tenant_id": tenant_id,
                    "user": request.user,
                    "request": request,
                    "operation": operation,
                },
            )
            rendered = converter.to_fhir(domain_instance, {"tenant_id": tenant_id})
            if rendered.errors or not rendered.fhir_resource:
                raise FHIRValidationError(
                    "The persisted domain record could not be rendered as FHIR.",
                    diagnostics="; ".join(rendered.errors),
                )

            from apps.fhir.services.resource_meta import apply_declared_profiles

            rendered.fhir_resource = apply_declared_profiles(
                rendered.fhir_resource,
                resource_type,
                extra=registration.supported_profiles,
            )

            response_status = (
                status.HTTP_200_OK
                if operation == "update" and existed_before
                else status.HTTP_201_CREATED
            )
            if idempotency_record:
                idempotency_record.resource_id = domain_instance.id
                idempotency_record.state = FHIRIdempotencyRecord.STATE_COMPLETED
                idempotency_record.response_status = response_status
                idempotency_record.save(
                    update_fields=["resource_id", "state", "response_status", "updated_at"]
                )
            actor_id = getattr(request.user, "id", None)
            log_audit(
                tenant_id=tenant_id,
                action=f"FHIR_{operation.upper()}",
                model_name=resource_type,
                object_id=str(domain_instance.id),
                user_id=actor_id,
                metadata={
                    "interaction": operation,
                    "idempotency_key_present": bool(idempotency_key),
                },
            )
            emit_event(
                tenant_id=tenant_id,
                aggregate_type=resource_type,
                aggregate_id=domain_instance.id,
                event_type=f"fhir.{resource_type.lower()}.{operation}",
                payload={
                    "resource_type": resource_type,
                    "resource_id": str(domain_instance.id),
                    "operation": operation,
                },
                auto_process=False,
            )

        response = Response(
            rendered.fhir_resource.dict(exclude_none=True),
            status=response_status,
        )
        response["Location"] = request.build_absolute_uri(
            f"/api/fhir/r4/{resource_type}/{domain_instance.id}"
        )
        return response

    @staticmethod
    def _claim_idempotency(
        *,
        tenant_id,
        key: str,
        request_hash: str,
        resource_type: str,
        operation: str,
        actor_id=None,
    ) -> tuple[FHIRIdempotencyRecord, bool]:
        record = FHIRIdempotencyRecord.all_objects.select_for_update().filter(
            tenant_id=tenant_id,
            key=key,
        ).first()
        if record is None:
            try:
                with transaction.atomic():
                    record = FHIRIdempotencyRecord.all_objects.create(
                        tenant_id=tenant_id,
                        key=key,
                        request_hash=request_hash,
                        resource_type=resource_type,
                        operation=operation,
                        actor_id=actor_id,
                    )
                return record, False
            except IntegrityError:
                record = FHIRIdempotencyRecord.all_objects.select_for_update().get(
                    tenant_id=tenant_id,
                    key=key,
                )

        if (
            record.request_hash != request_hash
            or record.resource_type != resource_type
            or record.operation != operation
        ):
            raise FHIRIdempotencyError(
                "Idempotency-Key was already used for a different FHIR request."
            )
        if record.state == FHIRIdempotencyRecord.STATE_COMPLETED:
            return record, True
        raise FHIRIdempotencyError("An identical FHIR request is already being processed.")

    def _evaluate_cds_for_medication_request(self, domain_command: dict, fhir_instance: Any) -> Any:
        # MedicationRequest persistence creates only a DRAFT prescription. DawaTrace CDS
        # runs at the explicit CLINICAL_REVIEW transition, where complete patient context
        # and an auditable knowledge release are mandatory. An inbound extension cannot
        # downgrade or bypass that gate.
        return None
