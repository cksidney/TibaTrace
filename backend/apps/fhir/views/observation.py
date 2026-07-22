from apps.fhir.api.generic import FHIRReadView, FHIRSearchView
from apps.fhir.api.write_generic import FHIRWriteView


class ObservationView(FHIRReadView, FHIRSearchView, FHIRWriteView):
    fhir_resource_type = "Observation"
