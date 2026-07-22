from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from fhir.resources.parameters import Parameters
from fhir.resources.valueset import ValueSet
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.fhir.api.generic import FHIRReadView, FHIRSearchView
from apps.fhir.api.write_generic import FHIRWriteView
from apps.fhir.constants import PERMISSION_TERMINOLOGY_EXPAND, PERMISSION_TERMINOLOGY_VALIDATE
from apps.fhir.converters.value_set import ValueSetConverter
from apps.fhir.exceptions import FHIRSecurityError, FHIRValidationError
from apps.fhir.views.terminology_parameters import (
    boolean_value,
    coding_values,
    parameter_values,
    parameters_result,
    terminology_as_of,
)
from apps.terminology.models import FHIRCodeSystemRegistration, FHIRValueSetRegistration


def _scope(tenant_id):
    return Q(tenant_id=tenant_id) | Q(tenant__isnull=True, version__is_global=True)


def _effective_at(queryset, as_of):
    if not as_of:
        return queryset
    return queryset.filter(
        Q(version__effective_period_start__isnull=True)
        | Q(version__effective_period_start__lte=as_of),
    ).filter(
        Q(version__effective_period_end__isnull=True)
        | Q(version__effective_period_end__gte=as_of),
    )


def _value_set(tenant_id, url, version=None, *, as_of=None):
    queryset = FHIRValueSetRegistration.all_objects.filter(
        _scope(tenant_id),
        version__status__iexact="ACTIVE",
        url=url,
    ).select_related("version")
    queryset = _effective_at(queryset, as_of)
    if version:
        queryset = queryset.filter(version__version=version)
    ordering = ("-version__effective_period_start", "-created_at")
    return (
        queryset.filter(tenant_id=tenant_id).order_by(*ordering).first()
        or queryset.filter(tenant__isnull=True, version__is_global=True).order_by(*ordering).first()
    )


def _code_system(tenant_id, system, version=None, *, as_of=None):
    queryset = FHIRCodeSystemRegistration.all_objects.filter(
        _scope(tenant_id),
        version__status__iexact="ACTIVE",
        url=system,
    ).select_related("version")
    queryset = _effective_at(queryset, as_of)
    if version:
        queryset = queryset.filter(version__version=version)
    ordering = ("-version__effective_period_start", "-created_at")
    return (
        queryset.filter(tenant_id=tenant_id).order_by(*ordering).first()
        or queryset.filter(tenant__isnull=True, version__is_global=True).order_by(*ordering).first()
    )


def _system_concepts(tenant_id, system, version=None, *, active_only=False, as_of=None):
    code_system = _code_system(tenant_id, system, version, as_of=as_of)
    if not code_system:
        raise FHIRValidationError("ValueSet references an unknown CodeSystem or version.")
    rows = list(code_system.concepts_json or [])
    if active_only:
        rows = [row for row in rows if row.get("inactive") is not True]
    return code_system, rows


def _split_canonical(value: str) -> tuple[str, str | None]:
    url, separator, version = str(value).partition("|")
    return url, version if separator else None


def _enforce_expansion_limit(rows):
    if len(rows) > settings.FHIR_TERMINOLOGY_EXPANSION_ABSOLUTE_MAX:
        raise FHIRValidationError("ValueSet expansion exceeds the configured absolute size limit.")


def _inline_value_set(resource):
    if getattr(resource, "resource_type", None) != "ValueSet":
        raise FHIRValidationError("valueSet parameter must contain a ValueSet resource.")
    payload = resource.dict(exclude_none=True)
    compose = payload.get("compose") or {}
    marker = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return SimpleNamespace(
        id=f"inline-{marker}",
        url=payload.get("url") or f"urn:uuid:{marker}",
        name=payload.get("name") or "InlineValueSet",
        title=payload.get("title"),
        compose_json=compose,
        version=SimpleNamespace(
            version=payload.get("version") or "",
            status=(payload.get("status") or "active").upper(),
            publisher=payload.get("publisher"),
            effective_period_start=None,
        ),
        source_resource=resource,
    )


def _resolve_value_set(values, tenant_id, *, as_of=None):
    inline = values.get("valueSet")
    if inline is not None:
        return _inline_value_set(inline)
    url = str(values.get("url") or "")
    version = str(values.get("valueSetVersion") or values.get("version") or "") or None
    if not url:
        raise FHIRValidationError("url or valueSet parameter is required")
    value_set = _value_set(tenant_id, url, version, as_of=as_of)
    if not value_set:
        raise FHIRValidationError("ValueSet was not found in the active scope and version.")
    return value_set


def _expansion_rows(
    value_set,
    tenant_id,
    *,
    active_only=False,
    visited=None,
    deadline=None,
    as_of=None,
):
    if deadline is not None and time.monotonic() > deadline:
        raise FHIRValidationError("ValueSet expansion exceeded its configured time limit.")
    visited = set(visited or set())
    marker = str(value_set.id)
    if marker in visited:
        raise FHIRValidationError("Circular ValueSet import detected.")
    path = {*visited, marker}

    compose = value_set.compose_json or {}
    rows: dict[tuple[str, str], dict] = {}
    for include in compose.get("include", []):
        if include.get("filter"):
            raise FHIRValidationError("ValueSet compose filters are not supported for local expansion.")
        system = include.get("system")
        version = include.get("version")
        concepts = include.get("concept")
        code_system = None
        installed = None
        if system:
            code_system, installed = _system_concepts(
                tenant_id,
                system,
                version,
                active_only=active_only,
                as_of=as_of,
            )
        if concepts is None and system:
            concepts = installed
        installed_by_code = {
            str(row.get("code") or ""): row
            for row in installed or []
        }
        for concept in concepts or []:
            code = str(concept.get("code") or "")
            if not system or not code:
                continue
            source = installed_by_code.get(code, concept)
            if active_only and source.get("inactive") is True:
                continue
            rows[(system, code)] = {
                "system": system,
                "version": version or (code_system.version.version if code_system else ""),
                "code": code,
                "display": concept.get("display") or source.get("display") or "",
                "inactive": source.get("inactive") is True,
                "abstract": source.get("abstract") is True,
            }
            _enforce_expansion_limit(rows)
        for imported_canonical in include.get("valueSet", []) or []:
            imported_url, imported_version = _split_canonical(imported_canonical)
            imported = _value_set(
                tenant_id,
                imported_url,
                imported_version,
                as_of=as_of,
            )
            if not imported:
                raise FHIRValidationError("Imported ValueSet was not found in the active scope.")
            for row in _expansion_rows(
                imported,
                tenant_id,
                active_only=active_only,
                visited=path,
                deadline=deadline,
                as_of=as_of,
            ):
                rows[(row["system"], row["code"])] = row
                _enforce_expansion_limit(rows)

    for exclude in compose.get("exclude", []):
        if exclude.get("filter"):
            raise FHIRValidationError("ValueSet compose filters are not supported for local expansion.")
        system = exclude.get("system")
        concepts = exclude.get("concept")
        if concepts is None and system:
            _, concepts = _system_concepts(
                tenant_id,
                system,
                exclude.get("version"),
                active_only=False,
                as_of=as_of,
            )
        for concept in concepts or []:
            rows.pop((system, str(concept.get("code") or "")), None)
        for imported_canonical in exclude.get("valueSet", []) or []:
            imported_url, imported_version = _split_canonical(imported_canonical)
            imported = _value_set(
                tenant_id,
                imported_url,
                imported_version,
                as_of=as_of,
            )
            if not imported:
                raise FHIRValidationError("Excluded ValueSet was not found in the active scope.")
            for row in _expansion_rows(
                imported,
                tenant_id,
                active_only=False,
                visited=path,
                deadline=deadline,
                as_of=as_of,
            ):
                rows.pop((row["system"], row["code"]), None)

    return sorted(rows.values(), key=lambda row: (row["system"], row["version"], row["code"]))


def _cached_rows(value_set, tenant_id, *, active_only, as_of=None):
    timeout_seconds = float(getattr(settings, "FHIR_TERMINOLOGY_EXPANSION_TIMEOUT_SECONDS", 5.0))
    key_payload = {
        "tenant": str(tenant_id),
        "id": str(value_set.id),
        "url": value_set.url,
        "version": value_set.version.version,
        "compose": value_set.compose_json,
        "activeOnly": active_only,
        "date": as_of.isoformat() if as_of else "",
    }
    digest = hashlib.sha256(json.dumps(key_payload, sort_keys=True, default=str).encode()).hexdigest()
    cache_key = f"fhir:valueset:expand:{digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    rows = _expansion_rows(
        value_set,
        tenant_id,
        active_only=active_only,
        deadline=time.monotonic() + timeout_seconds,
        as_of=as_of,
    )
    cache.set(
        cache_key,
        rows,
        timeout=int(getattr(settings, "FHIR_TERMINOLOGY_EXPANSION_CACHE_SECONDS", 300)),
    )
    return rows


class ValueSetView(FHIRReadView, FHIRSearchView, FHIRWriteView):
    fhir_resource_type = "ValueSet"


class ValueSetValidateCodeView(FHIRReadView):
    fhir_resource_type = "ValueSet"
    required_capability = PERMISSION_TERMINOLOGY_VALIDATE
    supported_parameters = {
        "url",
        "valueSet",
        "valueSetVersion",
        "version",
        "code",
        "system",
        "systemVersion",
        "display",
        "coding",
        "codeableConcept",
        "date",
        "abstract",
        "displayLanguage",
    }

    def get(self, request, *args, **kwargs):
        return self._execute(request.query_params)

    def post(self, request, *args, **kwargs):
        if request.data.get("resourceType") != "Parameters":
            raise FHIRValidationError("Expected Parameters resource")
        Parameters.parse_obj(request.data)
        return self._execute(request.data)

    def _execute(self, payload):
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            raise FHIRSecurityError("Missing tenant context.", code="forbidden")
        values = parameter_values(payload)
        unsupported = sorted(set(values) - self.supported_parameters)
        if unsupported:
            raise FHIRValidationError(
                "Unsupported ValueSet/$validate-code parameter.",
                diagnostics=", ".join(unsupported),
            )
        as_of = terminology_as_of(values.get("date"))
        value_set = _resolve_value_set(values, tenant_id, as_of=as_of)
        system, code, system_version, requested_display = coding_values(values)
        if not code:
            raise FHIRValidationError("code, coding, or codeableConcept is required")
        rows = _cached_rows(value_set, tenant_id, active_only=False, as_of=as_of)
        match = next(
            (
                row
                for row in rows
                if row["code"] == code
                and (not system or row["system"] == system)
                and (not system_version or row.get("version") in {"", system_version})
            ),
            None,
        )
        if match and match.get("inactive"):
            return Response(
                parameters_result(
                    result=False,
                    message="Code is inactive in the ValueSet expansion.",
                    display=match.get("display", ""),
                    code=code,
                    system=match["system"],
                    version=match.get("version", ""),
                )
            )
        if match and not boolean_value(values.get("abstract"), default=True) and match.get("abstract"):
            match = None
        if match and requested_display and requested_display != match.get("display"):
            return Response(
                parameters_result(
                    result=False,
                    message="Display does not match the canonical display.",
                    display=match.get("display", ""),
                    code=code,
                    system=match["system"],
                    version=match.get("version", ""),
                )
            )
        return Response(
            parameters_result(
                result=match is not None,
                message="Code is not in the ValueSet." if match is None else "",
                display=match.get("display", "") if match else "",
                code=code,
                system=match["system"] if match else system,
                version=match.get("version", "") if match else system_version,
            )
        )


class ValueSetExpandView(FHIRReadView):
    fhir_resource_type = "ValueSet"
    required_capability = PERMISSION_TERMINOLOGY_EXPAND
    supported_parameters = {
        "url",
        "valueSet",
        "valueSetVersion",
        "version",
        "filter",
        "date",
        "offset",
        "count",
        "activeOnly",
        "displayLanguage",
    }

    def get(self, request, *args, **kwargs):
        return self._execute(request.query_params)

    def post(self, request, *args, **kwargs):
        if request.data.get("resourceType") != "Parameters":
            raise FHIRValidationError("Expected Parameters resource")
        Parameters.parse_obj(request.data)
        return self._execute(request.data)

    def _execute(self, payload):
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            raise FHIRSecurityError("Missing tenant context.", code="forbidden")
        values = parameter_values(payload)
        unsupported = sorted(set(values) - self.supported_parameters)
        if unsupported:
            raise FHIRValidationError(
                "Unsupported ValueSet/$expand parameter.",
                diagnostics=", ".join(unsupported),
            )
        as_of = terminology_as_of(values.get("date"))
        value_set = _resolve_value_set(values, tenant_id, as_of=as_of)
        active_only = boolean_value(values.get("activeOnly"), default=False)
        rows = _cached_rows(value_set, tenant_id, active_only=active_only, as_of=as_of)
        filter_text = str(values.get("filter") or "").strip().casefold()
        if filter_text:
            rows = [
                row
                for row in rows
                if filter_text in row["code"].casefold()
                or filter_text in str(row.get("display") or "").casefold()
            ]
        try:
            offset = max(0, int(values.get("offset") or 0))
            requested_count = int(values.get("count") or settings.FHIR_TERMINOLOGY_EXPANSION_MAX)
        except (TypeError, ValueError) as exc:
            raise FHIRValidationError("offset and count must be integers.") from exc
        if requested_count < 1:
            raise FHIRValidationError("count must be greater than zero.")
        count = min(requested_count, settings.FHIR_TERMINOLOGY_EXPANSION_MAX)
        page = rows[offset:offset + count]
        contains = [
            {
                key: value
                for key, value in row.items()
                if key in {"system", "version", "code", "display", "inactive", "abstract"}
                and value not in {"", False, None}
            }
            for row in page
        ]

        if hasattr(value_set, "source_resource"):
            rendered_resource = ValueSet.parse_obj(value_set.source_resource.dict(exclude_none=True))
        else:
            rendered = ValueSetConverter().to_fhir(value_set, {"tenant_id": tenant_id})
            if rendered.errors or not rendered.fhir_resource:
                raise FHIRValidationError("ValueSet could not be rendered for expansion.")
            rendered_resource = rendered.fhir_resource
        rendered_resource.expansion = {
            "identifier": f"urn:uuid:{hashlib.sha256((str(value_set.id) + str(tenant_id)).encode()).hexdigest()[:32]}",
            "timestamp": timezone.now().isoformat(),
            "total": len(rows),
            "offset": offset,
            "contains": contains,
        }
        return Response(rendered_resource.dict(exclude_none=True))
