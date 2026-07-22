from apps.fhir.api.generic import FHIRReadView
from apps.fhir.api.write_generic import FHIRWriteView


class MedicationRequestView(FHIRReadView, FHIRWriteView):
    fhir_resource_type = "MedicationRequest"
