from apps.fhir.api.generic import FHIRReadView
from apps.fhir.api.write_generic import FHIRWriteView


class PatientReadView(FHIRReadView, FHIRWriteView):
    fhir_resource_type = "Patient"
