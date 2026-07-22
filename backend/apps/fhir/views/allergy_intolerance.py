from apps.fhir.api.generic import FHIRReadView, FHIRSearchView
from apps.fhir.api.write_generic import FHIRWriteView


class AllergyIntoleranceView(FHIRReadView, FHIRSearchView, FHIRWriteView):
    fhir_resource_type = "AllergyIntolerance"
