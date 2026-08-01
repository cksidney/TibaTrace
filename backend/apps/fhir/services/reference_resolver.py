from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from django.conf import settings

from apps.audit.service import log_audit
from apps.fhir.exceptions import FHIRReferenceResolutionError, FHIRSecurityError


class FHIRReferenceResolver:
    """Tenant-qualified resolver for local FHIR references."""

    RELATIVE_REF_PATTERN = re.compile(r"^([A-Za-z][A-Za-z0-9]*)/([A-Za-z0-9\-.]+)$")
    CONDITIONAL_REF_PATTERN = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\?(.+)$")

    @staticmethod
    def _require_tenant(tenant_id: str | None) -> str:
        value = str(tenant_id or "").strip()
        if not value:
            raise FHIRSecurityError("Missing tenant context.", code="forbidden")
        return value

    @staticmethod
    def _audit(tenant_id: str, resource_type: str, lookup: str, result: str, user_id=None) -> None:
        log_audit(
            tenant_id=tenant_id,
            action="FHIR_REFERENCE_RESOLVE",
            model_name=resource_type,
            object_id=lookup[:120],
            user_id=user_id,
            metadata={"result": result},
        )

    @classmethod
    def resolve(
        cls,
        reference: Any,
        expected_type: str | None,
        tenant_id: str,
        bundle_context: dict[str, Any] | None = None,
        *,
        user_id=None,
    ) -> Any:
        tenant_id = cls._require_tenant(tenant_id)
        bundle_context = bundle_context or {}

        reference_value = getattr(reference, "reference", reference)
        identifier = getattr(reference, "identifier", None)
        if isinstance(reference, dict):
            reference_value = reference.get("reference")
            identifier = reference.get("identifier")

        if not reference_value and identifier:
            return cls.resolve_identifier_for_tenant(
                tenant_id,
                expected_type,
                identifier,
                user_id=user_id,
            )
        if not reference_value:
            return None

        reference_value = str(reference_value).strip()
        if reference_value.startswith("urn:uuid:"):
            target = bundle_context.get(reference_value)
            if target is None:
                cls._audit(tenant_id, expected_type or "Resource", reference_value, "not_found", user_id)
                raise FHIRReferenceResolutionError(
                    "Bundle-local reference could not be resolved.",
                    code="not-found",
                )
            target_type = getattr(target, "resource_type", None) or getattr(target, "resourceType", None)
            if expected_type and target_type != expected_type:
                raise FHIRReferenceResolutionError(
                    "Bundle-local reference type does not match the expected resource type.",
                    code="invalid",
                )
            cls._audit(tenant_id, expected_type or target_type or "Resource", reference_value, "bundle_local", user_id)
            return target

        if reference_value.startswith("#"):
            target = bundle_context.get(reference_value)
            if target is None:
                cls._audit(tenant_id, expected_type or "Resource", reference_value, "not_found", user_id)
                raise FHIRReferenceResolutionError("Contained reference could not be resolved.", code="not-found")
            target_type = getattr(target, "resource_type", None) or getattr(target, "resourceType", None)
            if expected_type and target_type != expected_type:
                raise FHIRReferenceResolutionError("Contained reference type mismatch.", code="invalid")
            cls._audit(tenant_id, expected_type or target_type or "Resource", reference_value, "contained", user_id)
            return target

        parsed = urlparse(reference_value)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme not in {"http", "https"}:
                raise FHIRReferenceResolutionError("Unsupported absolute reference scheme.", code="invalid")
            allowed_hosts = set(getattr(settings, "FHIR_ALLOWED_ABSOLUTE_REFERENCE_HOSTS", []) or [])
            try:
                from apps.fhir.kenya_hie import DEFAULT_HIE_REFERENCE_HOSTS

                allowed_hosts.update(DEFAULT_HIE_REFERENCE_HOSTS)
            except ImportError:
                pass
            if parsed.hostname not in allowed_hosts:
                raise FHIRReferenceResolutionError(
                    "External reference host is not permitted for local resolution.",
                    code="not-supported",
                )
            path_parts = [unquote(part) for part in parsed.path.split("/") if part]
            if len(path_parts) < 2:
                raise FHIRReferenceResolutionError("Absolute reference path is invalid.", code="invalid")
            reference_value = "/".join(path_parts[-2:])

        conditional = cls.CONDITIONAL_REF_PATTERN.fullmatch(reference_value)
        if conditional:
            resource_type, query = conditional.groups()
            if expected_type and resource_type != expected_type:
                raise FHIRReferenceResolutionError("Conditional reference type mismatch.", code="invalid")
            parameters = parse_qs(query, keep_blank_values=False)
            identifiers = parameters.get("identifier", [])
            if len(identifiers) != 1 or len(parameters) != 1:
                raise FHIRReferenceResolutionError(
                    "Only a single identifier conditional reference is supported.",
                    code="not-supported",
                )
            return cls.resolve_identifier_for_tenant(
                tenant_id,
                resource_type,
                identifiers[0],
                user_id=user_id,
            )

        match = cls.RELATIVE_REF_PATTERN.fullmatch(reference_value)
        if not match:
            raise FHIRReferenceResolutionError(
                "Reference format is invalid.",
                diagnostics="Expected ResourceType/id, an allowed absolute URL, urn:uuid, or a contained reference.",
                code="invalid",
            )
        resource_type, resource_id = match.groups()
        if expected_type and resource_type != expected_type:
            raise FHIRReferenceResolutionError("Reference type mismatch.", code="invalid")
        return cls.resolve_for_tenant(
            tenant_id,
            resource_type,
            resource_id,
            user_id=user_id,
        )

    @classmethod
    def resolve_for_tenant(
        cls,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        *,
        user_id=None,
    ) -> Any:
        tenant_id = cls._require_tenant(tenant_id)
        from apps.fhir.services.resource_registry import FHIRResourceRegistry

        try:
            registration = FHIRResourceRegistry.get_registration(resource_type)
        except Exception as exc:
            raise FHIRReferenceResolutionError("Unsupported reference resource type.", code="not-supported") from exc
        instance = registration.service_class.get_by_id(resource_id, tenant_id=tenant_id)
        if instance is None:
            cls._audit(tenant_id, resource_type, resource_id, "not_found", user_id)
            raise FHIRReferenceResolutionError(
                "Referenced resource was not found in the active tenant.",
                code="not-found",
            )
        cls._audit(tenant_id, resource_type, resource_id, "resolved", user_id)
        return instance

    @classmethod
    def resolve_identifier_for_tenant(
        cls,
        tenant_id: str,
        resource_type: str | None,
        identifier: Any,
        *,
        user_id=None,
    ) -> Any:
        tenant_id = cls._require_tenant(tenant_id)
        if not resource_type:
            raise FHIRReferenceResolutionError("Identifier reference requires a resource type.", code="invalid")
        if isinstance(identifier, str):
            system, separator, value = identifier.partition("|")
            if not separator:
                system, value = "", system
        elif isinstance(identifier, dict):
            system = str(identifier.get("system") or "")
            value = str(identifier.get("value") or "")
        else:
            system = str(getattr(identifier, "system", "") or "")
            value = str(getattr(identifier, "value", "") or "")
        if not value:
            raise FHIRReferenceResolutionError("Identifier value is required.", code="invalid")

        from apps.fhir.services.resource_registry import FHIRResourceRegistry

        try:
            registration = FHIRResourceRegistry.get_registration(resource_type)
        except Exception as exc:
            raise FHIRReferenceResolutionError("Unsupported identifier resource type.", code="not-supported") from exc
        resolver = getattr(registration.service_class, "get_by_identifier", None)
        if not callable(resolver):
            raise FHIRReferenceResolutionError(
                "Identifier-based resolution is not supported for this resource type.",
                code="not-supported",
            )
        instance = resolver(system=system, value=value, tenant_id=tenant_id)
        lookup = f"{system}|{value}" if system else value
        if instance is None:
            cls._audit(tenant_id, resource_type, lookup, "not_found", user_id)
            raise FHIRReferenceResolutionError(
                "Referenced identifier was not found in the active tenant.",
                code="not-found",
            )
        cls._audit(tenant_id, resource_type, lookup, "resolved", user_id)
        return instance
