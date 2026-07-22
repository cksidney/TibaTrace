from typing import Any, Dict

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.diagnosticreport import DiagnosticReport
from fhir.resources.reference import Reference

from apps.clinical.models import ClinicalDiagnosticReport, ClinicalObservation
from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult


class DiagnosticReportConverter(BaseFHIRConverter):
    resource_type = "DiagnosticReport"

    def to_fhir(self, domain_object: ClinicalDiagnosticReport, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            status = domain_object.status.lower().replace("_", "-")

            code = CodeableConcept(
                coding=[Coding(code=domain_object.code, system=domain_object.system, display=domain_object.display)]
            )

            report = DiagnosticReport(
                id=str(domain_object.id),
                status=status,
                code=code,
                subject=Reference(reference=f"Patient/{domain_object.patient_id}")
            )

            if domain_object.encounter_id:
                report.encounter = Reference(reference=f"Encounter/{domain_object.encounter_id}")

            if domain_object.category:
                report.category = [CodeableConcept(coding=[Coding(code=domain_object.category)])]

            if domain_object.effective_time:
                report.effectiveDateTime = domain_object.effective_time.isoformat()

            if domain_object.conclusion:
                report.conclusion = domain_object.conclusion

            observations = list(
                ClinicalObservation.all_objects.filter(
                    diagnostic_reports=domain_object,
                    tenant_id=context.get("tenant_id"),
                )
            )
            if observations:
                report.result = [Reference(reference=f"Observation/{obs.id}") for obs in observations]

            result.fhir_resource = report
        except Exception:
            result.add_exception("Clinical report could not be rendered as DiagnosticReport.")

        return result

    def to_domain_command(self, resource: DiagnosticReport, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            patient_id = resource.subject.reference.split("/")[-1] if resource.subject and resource.subject.reference else None
            if not patient_id:
                result.add_error("Subject (Patient) reference is required.")
                return result

            status = resource.status.upper().replace("-", "_")

            encounter_id = None
            if resource.encounter and resource.encounter.reference:
                encounter_id = resource.encounter.reference.split("/")[-1]

            category = None
            if resource.category and len(resource.category) > 0 and resource.category[0].coding:
                category = resource.category[0].coding[0].code

            code = None
            system = None
            display = None
            if resource.code and resource.code.coding:
                code = resource.code.coding[0].code
                system = resource.code.coding[0].system
                display = resource.code.coding[0].display or resource.code.text

            effective_time = resource.effectiveDateTime if hasattr(resource, "effectiveDateTime") and resource.effectiveDateTime else None

            conclusion = resource.conclusion

            observations = []
            if resource.result:
                observations = [ref.reference.split("/")[-1] for ref in resource.result if ref.reference]

            result.domain_command = {
                "resource_type": "DiagnosticReport",
                "id": resource.id,
                "patient_id": patient_id,
                "status": status,
                "encounter_id": encounter_id,
                "category": category,
                "code": code,
                "system": system,
                "display": display,
                "effective_time": effective_time,
                "conclusion": conclusion,
                "observations": observations
            }
        except Exception:
            result.add_exception("DiagnosticReport could not be mapped to a domain command.")

        return result
