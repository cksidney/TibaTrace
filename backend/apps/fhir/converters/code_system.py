from typing import Any, Dict

from fhir.resources.codesystem import CodeSystem

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.terminology.models import FHIRCodeSystemRegistration


class CodeSystemConverter(BaseFHIRConverter):
    resource_type = "CodeSystem"

    def to_fhir(self, domain_object: FHIRCodeSystemRegistration, context: Dict[str, Any]) -> ConversionResult:
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
                caseSensitive=True,
                content=domain_object.content_mode.lower().replace("_", "-"),
            )
            if domain_object.title:
                payload["title"] = domain_object.title
            cs = CodeSystem(**payload)

            if domain_object.version and domain_object.version.publisher:
                cs.publisher = domain_object.version.publisher
            if domain_object.version and domain_object.version.effective_period_start:
                cs.date = domain_object.version.effective_period_start.isoformat()

            if domain_object.concepts_json and isinstance(domain_object.concepts_json, list):
                concepts = []
                has_inactive = False
                for row in domain_object.concepts_json:
                    concept = {
                        key: row.get(key)
                        for key in ("code", "display", "definition")
                        if row.get(key) is not None
                    }
                    if row.get("inactive") is True:
                        has_inactive = True
                        concept["property"] = [
                            {"code": "inactive", "valueBoolean": True}
                        ]
                    concepts.append(concept)
                if has_inactive:
                    cs.property = [
                        {
                            "code": "inactive",
                            "uri": "http://hl7.org/fhir/concept-properties#inactive",
                            "description": "Whether the concept is inactive.",
                            "type": "boolean",
                        }
                    ]
                cs.concept = concepts
                cs.count = len(concepts)

            result.fhir_resource = cs
        except Exception:
            result.add_exception("Registered terminology could not be rendered as CodeSystem.")

        return result

    def to_domain_command(self, resource: CodeSystem, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        result.add_error("CodeSystem modification via FHIR is not supported.")
        return result
