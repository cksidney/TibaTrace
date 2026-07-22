from apps.fhir.api.generic import FHIRReadView


class MedicationStatementView(FHIRReadView):
    fhir_resource_type = "MedicationStatement"
