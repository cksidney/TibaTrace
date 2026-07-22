from apps.fhir.api.generic import FHIRReadView


class MedicationReadView(FHIRReadView):
    fhir_resource_type = "Medication"
