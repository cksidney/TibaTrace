from __future__ import annotations

from django.db.models import Q
from fhir.resources.parameters import Parameters
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.fhir.api.generic import FHIRReadView, FHIRSearchView
from apps.fhir.api.write_generic import FHIRWriteView
from apps.fhir.constants import PERMISSION_TERMINOLOGY_VALIDATE
from apps.fhir.exceptions import FHIRSecurityError, FHIRValidationError
from apps.fhir.views.terminology_parameters import (
    boolean_value,
    coding_values,
    parameter_values,
    parameters_result,
    terminology_as_of,
)
from apps.terminology.models import FHIRCodeSystemRegistration


class CodeSystemView(FHIRReadView, FHIRSearchView, FHIRWriteView):
    fhir_resource_type = "CodeSystem"


class CodeSystemValidateCodeView(FHIRReadView):
    fhir_resource_type = "CodeSystem"
    required_capability = PERMISSION_TERMINOLOGY_VALIDATE
    supported_parameters = {
        "url",
        "code",
        "system",
        "systemVersion",
        "version",
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
                "Unsupported CodeSystem/$validate-code parameter.",
                diagnostics=", ".join(unsupported),
            )

        system, code, coding_version, requested_display = coding_values(values)
        as_of = terminology_as_of(values.get("date"))
        url = str(values.get("url") or system or "")
        version = str(values.get("version") or values.get("systemVersion") or coding_version or "")
        if not url or not code:
            raise FHIRValidationError("A CodeSystem URL/system and code are required")
        if system and system != url:
            return Response(
                parameters_result(
                    result=False,
                    message="Coding system does not match the requested CodeSystem URL.",
                    code=code,
                    system=system,
                    version=version,
                )
            )

        queryset = FHIRCodeSystemRegistration.all_objects.filter(
            Q(tenant_id=tenant_id) | Q(tenant__isnull=True, version__is_global=True),
            version__status__iexact="ACTIVE",
            url=url,
        ).select_related("version")
        if as_of:
            queryset = queryset.filter(
                Q(version__effective_period_start__isnull=True)
                | Q(version__effective_period_start__lte=as_of),
            ).filter(
                Q(version__effective_period_end__isnull=True)
                | Q(version__effective_period_end__gte=as_of),
            )
        if version:
            queryset = queryset.filter(version__version=version)
        ordering = ("-version__effective_period_start", "-created_at")
        code_system = (
            queryset.filter(tenant_id=tenant_id).order_by(*ordering).first()
            or queryset.filter(tenant__isnull=True, version__is_global=True)
            .order_by(*ordering)
            .first()
        )
        if not code_system:
            return Response(
                parameters_result(
                    result=False,
                    message="CodeSystem was not found in the active scope and version.",
                    code=code,
                    system=url,
                    version=version,
                )
            )

        concept = next(
            (row for row in code_system.concepts_json or [] if str(row.get("code") or "") == code),
            None,
        )
        resolved_version = code_system.version.version
        if concept is None:
            return Response(
                parameters_result(
                    result=False,
                    message="Code is unknown in the requested CodeSystem version.",
                    code=code,
                    system=url,
                    version=resolved_version,
                )
            )
        display = str(concept.get("display") or "")
        if concept.get("inactive") is True:
            return Response(
                parameters_result(
                    result=False,
                    message="Code is inactive.",
                    display=display,
                    code=code,
                    system=url,
                    version=resolved_version,
                )
            )
        if not boolean_value(values.get("abstract"), default=True) and concept.get("abstract") is True:
            return Response(
                parameters_result(
                    result=False,
                    message="Code is abstract.",
                    display=display,
                    code=code,
                    system=url,
                    version=resolved_version,
                )
            )
        if requested_display and requested_display != display:
            return Response(
                parameters_result(
                    result=False,
                    message="Display does not match the canonical display.",
                    display=display,
                    code=code,
                    system=url,
                    version=resolved_version,
                )
            )
        return Response(
            parameters_result(
                result=True,
                display=display,
                code=code,
                system=url,
                version=resolved_version,
            )
        )
