from apps.fhir.api.generic import FHIRReadView, FHIRSearchView
from apps.fhir.api.write_generic import FHIRWriteView


class EncounterView(FHIRReadView, FHIRSearchView, FHIRWriteView):
    fhir_resource_type = "Encounter"
