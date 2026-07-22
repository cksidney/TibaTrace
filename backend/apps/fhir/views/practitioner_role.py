from apps.fhir.api.generic import FHIRReadView


class PractitionerRoleReadView(FHIRReadView):
    fhir_resource_type = "PractitionerRole"
