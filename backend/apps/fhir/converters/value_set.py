from typing import Any, Dict

from fhir.resources.valueset import ValueSet

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.terminology.models import FHIRValueSetRegistration


class ValueSetConverter(BaseFHIRConverter):
    resource_type = "ValueSet"

    def to_fhir(self, domain_object: FHIRValueSetRegistration, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            status = domain_object.version.status.lower() if domain_object.version else "active"

            payload = dict(
                id=str(domain_object.id),
                url=domain_object.url,
                version=domain_object.version.version if domain_object.version else "1.0",
                name=domain_object.name,
                status=status,
                experimental=False,
            )
            if domain_object.title:
                payload["title"] = domain_object.title
            vs = ValueSet(**payload)

            if domain_object.version and domain_object.version.publisher:
                vs.publisher = domain_object.version.publisher
            if domain_object.version and domain_object.version.effective_period_start:
                vs.date = domain_object.version.effective_period_start.isoformat()

            if domain_object.compose_json and isinstance(domain_object.compose_json, dict):
                vs.compose = domain_object.compose_json

            result.fhir_resource = vs
        except Exception:
            result.add_exception("Registered terminology could not be rendered as ValueSet.")

        return result

    def to_domain_command(self, resource: ValueSet, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        result.add_error("ValueSet modification via FHIR is not supported.")
        return result
