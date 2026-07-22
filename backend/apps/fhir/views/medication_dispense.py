from apps.fhir.api.generic import FHIRReadView
from apps.fhir.api.write_generic import FHIRWriteView


class MedicationDispenseView(FHIRReadView, FHIRWriteView):
    fhir_resource_type = "MedicationDispense"
