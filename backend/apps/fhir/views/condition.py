from apps.fhir.api.generic import FHIRReadView, FHIRSearchView
from apps.fhir.api.write_generic import FHIRWriteView


class ConditionView(FHIRReadView, FHIRSearchView, FHIRWriteView):
    fhir_resource_type = "Condition"
