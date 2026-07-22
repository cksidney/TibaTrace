import logging
import uuid
from typing import Any, Dict

import fhir.resources.bundle as fhir_bundle
from django.db import transaction

from apps.fhir.exceptions import (
    FHIRBusinessRuleError,
    FHIRException,
    FHIRIdempotencyError,
    FHIRNotSupportedError,
    FHIRReferenceResolutionError,
    FHIRSecurityError,
    FHIRValidationError,
)
from apps.fhir.services.operation_outcome import OperationOutcomeFactory
from apps.fhir.services.resource_registry import FHIRResourceRegistry

logger = logging.getLogger(__name__)

class BundleProcessor:
    """
    Processes FHIR Batch and Transaction Bundles.
    """

    @classmethod
    def process(cls, bundle: fhir_bundle.Bundle, tenant_id: str, user: Any) -> fhir_bundle.Bundle:
        if bundle.type not in ("batch", "transaction"):
            raise FHIRValidationError(
                message=f"Bundle type '{bundle.type}' is not supported for processing.",
                diagnostics="Supported types are 'batch' and 'transaction'."
            )

        if bundle.type == "transaction":
            return cls._process_transaction(bundle, tenant_id, user)
        else:
            return cls._process_batch(bundle, tenant_id, user)

    @classmethod
    def _process_transaction(cls, bundle: fhir_bundle.Bundle, tenant_id: str, user: Any) -> fhir_bundle.Bundle:
        bundle_context = cls._build_bundle_context(bundle)
        pending = list(enumerate(bundle.entry or []))
        completed_full_urls = set()
        responses = {}

        with transaction.atomic():
            while pending:
                progressed = False
                for index, entry in list(pending):
                    dependencies = cls._local_dependencies(entry, bundle_context)
                    if not dependencies.issubset(completed_full_urls):
                        continue
                    response_entry = cls._process_entry(
                        entry,
                        tenant_id,
                        bundle_context,
                        user,
                        allow_local_references=True,
                    )
                    response_status = response_entry.response.status if response_entry.response else "500"
                    if response_status.startswith(("4", "5")):
                        raise FHIRValidationError("Transaction aborted due to entry failure.")
                    responses[index] = response_entry
                    if entry.fullUrl:
                        completed_full_urls.add(entry.fullUrl)
                    pending.remove((index, entry))
                    progressed = True
                if not progressed:
                    raise FHIRReferenceResolutionError(
                        "Transaction contains unresolved or circular bundle-local references.",
                        code="not-found",
                    )

        return fhir_bundle.Bundle(
            type="transaction-response",
            entry=[responses[index] for index in sorted(responses)],
        )

    @classmethod
    def _process_batch(cls, bundle: fhir_bundle.Bundle, tenant_id: str, user: Any) -> fhir_bundle.Bundle:
        response_bundle = fhir_bundle.Bundle(
            type="batch-response",
            entry=[]
        )

        bundle_context = cls._build_bundle_context(bundle)

        for entry in bundle.entry or []:
            try:
                response_entry = cls._process_entry(
                    entry,
                    tenant_id,
                    bundle_context,
                    user,
                    allow_local_references=False,
                )
                response_bundle.entry.append(response_entry)
            except Exception as exc:
                # Batch semantics require independent entry failures. Keep expected
                # FHIR errors useful while redacting unexpected implementation details.
                response_bundle.entry.append(cls._create_exception_entry(exc, tenant_id))

        return response_bundle

    @classmethod
    def _build_bundle_context(cls, bundle: fhir_bundle.Bundle) -> Dict[str, Any]:
        """Builds a map of fullUrl -> resource for bundle-local resolution."""
        context = {}
        for entry in bundle.entry or []:
            if entry.fullUrl and entry.resource:
                if entry.fullUrl in context:
                    raise FHIRValidationError("Bundle fullUrl values must be unique.")
                if not entry.resource.id:
                    if entry.fullUrl.startswith("urn:uuid:"):
                        candidate = entry.fullUrl.removeprefix("urn:uuid:")
                        try:
                            uuid.UUID(candidate)
                            entry.resource.id = candidate
                        except ValueError:
                            entry.resource.id = str(uuid.uuid4())
                    else:
                        entry.resource.id = str(uuid.uuid4())
                context[entry.fullUrl] = entry.resource
        return context

    @staticmethod
    def _references(payload):
        references = set()
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key == "reference" and isinstance(value, str):
                    references.add(value)
                else:
                    references.update(BundleProcessor._references(value))
        elif isinstance(payload, list):
            for value in payload:
                references.update(BundleProcessor._references(value))
        return references

    @classmethod
    def _local_dependencies(cls, entry, bundle_context):
        references = cls._references(entry.resource.dict(exclude_none=True)) if entry.resource else set()
        unknown_urns = {
            reference
            for reference in references
            if reference.startswith("urn:uuid:") and reference not in bundle_context
        }
        if unknown_urns:
            raise FHIRReferenceResolutionError(
                "Bundle-local reference does not resolve to an entry fullUrl.",
                code="not-found",
            )
        return {reference for reference in references if reference in bundle_context}

    @classmethod
    def _resolve_local_references(cls, resource, bundle_context, *, allow_local_references):
        payload = resource.dict(exclude_none=True)

        def resolve(value):
            if isinstance(value, dict):
                resolved = {}
                for key, nested in value.items():
                    if key == "reference" and isinstance(nested, str) and nested in bundle_context:
                        if not allow_local_references:
                            raise FHIRReferenceResolutionError(
                                "Batch entries cannot depend on bundle-local resources.",
                                code="not-found",
                            )
                        target = bundle_context[nested]
                        resolved[key] = f"{target.resource_type}/{target.id}"
                    elif key == "reference" and isinstance(nested, str) and nested.startswith("urn:uuid:"):
                        raise FHIRReferenceResolutionError(
                            "Bundle-local reference does not resolve to an entry fullUrl.",
                            code="not-found",
                        )
                    else:
                        resolved[key] = resolve(nested)
                return resolved
            if isinstance(value, list):
                return [resolve(nested) for nested in value]
            return value

        return resource.__class__.parse_obj(resolve(payload))

    @classmethod
    def _process_entry(
        cls,
        entry: fhir_bundle.BundleEntry,
        tenant_id: str,
        bundle_context: Dict[str, Any],
        user: Any,
        *,
        allow_local_references: bool,
    ) -> fhir_bundle.BundleEntry:
        request = entry.request
        if not request:
            raise FHIRValidationError("Bundle entry missing request component.")

        method = request.method
        if method not in ("POST", "PUT"):
            # We only support POST and PUT for this foundation
            return cls._create_error_entry("405 Method Not Allowed", "Only POST/PUT supported in phase 7.0")

        resource = entry.resource
        if not resource:
            return cls._create_error_entry("400 Bad Request", "Missing resource in entry.")

        resource = cls._resolve_local_references(
            resource,
            bundle_context,
            allow_local_references=allow_local_references,
        )

        resource_type = resource.resource_type
        try:
            registration = FHIRResourceRegistry.get_registration(resource_type)
        except Exception:
            return cls._create_error_entry("400 Bad Request", f"Unsupported resource type: {resource_type}")

        if method == "POST" and not registration.interactions.create:
            return cls._create_error_entry("405 Method Not Allowed", f"Create not supported for {resource_type}")
        if method == "PUT" and not registration.interactions.update:
            return cls._create_error_entry("405 Method Not Allowed", f"Update not supported for {resource_type}")
        if method == "PUT":
            expected_prefix = f"{resource_type}/"
            if not request.url or not request.url.startswith(expected_prefix):
                return cls._create_error_entry(
                    "400 Bad Request",
                    "PUT bundle entries require a resource type and id URL.",
                )
            requested_id = request.url.removeprefix(expected_prefix)
            if not requested_id or "/" in requested_id:
                return cls._create_error_entry("400 Bad Request", "PUT resource id is invalid.")
            if resource.id and str(resource.id) != requested_id:
                return cls._create_error_entry(
                    "400 Bad Request",
                    "Resource id does not match the bundle request URL.",
                )
            resource.id = requested_id
        if registration.write_permission and (
            not hasattr(user, "has_capability")
            or not user.has_capability(registration.write_permission, tenant_id=tenant_id)
        ):
            raise FHIRSecurityError(
                f"Missing permission for {resource_type} write.",
                code="forbidden",
            )

        converter = registration.converter_class()
        conversion_context = {
            "tenant_id": tenant_id,
            "bundle_context": bundle_context
        }

        conversion_result = converter.to_domain_command(resource, conversion_context)
        if conversion_result.errors:
            return cls._create_error_entry("400 Bad Request", "; ".join(conversion_result.errors))

        domain_command = conversion_result.domain_command
        processor = getattr(registration.service_class, "process_domain_command", None)
        if not callable(processor):
            return cls._create_error_entry(
                "405 Method Not Allowed",
                f"Write processing is not implemented for {resource_type}",
            )

        domain_instance = processor(
            domain_command,
            {
                "tenant_id": tenant_id,
                "bundle_context": bundle_context,
                "user": user,
                "operation": "create" if method == "POST" else "update",
            },
        )
        result_id = str(domain_instance.id)

        location = f"{resource_type}/{result_id}"

        rendered = converter.to_fhir(domain_instance, {"tenant_id": tenant_id})
        if rendered.errors or not rendered.fhir_resource:
            raise FHIRValidationError(
                "Persisted bundle resource could not be rendered as FHIR.",
                diagnostics="; ".join(rendered.errors),
            )

        return fhir_bundle.BundleEntry(
            resource=rendered.fhir_resource,
            response=fhir_bundle.BundleEntryResponse(
                status="201 Created" if method == "POST" else "200 OK",
                location=location
            )
        )

    @classmethod
    def _create_error_entry(cls, status: str, message: str) -> fhir_bundle.BundleEntry:
        outcome = OperationOutcomeFactory.create_error(message=message, code="processing")
        return fhir_bundle.BundleEntry(
            response=fhir_bundle.BundleEntryResponse(
                status=status,
                outcome=outcome
            )
        )

    @classmethod
    def _create_exception_entry(cls, exc: Exception, tenant_id: str) -> fhir_bundle.BundleEntry:
        status_by_exception = {
            FHIRSecurityError: "403 Forbidden",
            FHIRNotSupportedError: "405 Method Not Allowed",
            FHIRIdempotencyError: "409 Conflict",
            FHIRBusinessRuleError: "422 Unprocessable Entity",
            FHIRReferenceResolutionError: "422 Unprocessable Entity",
            FHIRValidationError: "400 Bad Request",
        }

        if isinstance(exc, FHIRException):
            status = next(
                (value for error_type, value in status_by_exception.items() if isinstance(exc, error_type)),
                "400 Bad Request",
            )
            outcome = OperationOutcomeFactory.from_exception(exc)
        else:
            logger.error(
                "Unexpected FHIR batch entry failure for tenant %s; exception_type=%s",
                tenant_id,
                type(exc).__name__,
            )
            status = "500 Internal Server Error"
            outcome = OperationOutcomeFactory.from_exception(exc)

        return fhir_bundle.BundleEntry(
            response=fhir_bundle.BundleEntryResponse(
                status=status,
                outcome=outcome,
            )
        )
