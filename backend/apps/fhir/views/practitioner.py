from apps.fhir.api.generic import FHIRReadView


class PractitionerReadView(FHIRReadView):
    fhir_resource_type = "Practitioner"
