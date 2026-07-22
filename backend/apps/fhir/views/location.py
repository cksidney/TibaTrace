from apps.fhir.api.generic import FHIRReadView


class LocationReadView(FHIRReadView):
    fhir_resource_type = "Location"
