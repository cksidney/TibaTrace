from apps.fhir.api.generic import FHIRReadView


class OrganizationReadView(FHIRReadView):
    fhir_resource_type = "Organization"
