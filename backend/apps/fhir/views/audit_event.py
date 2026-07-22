from apps.fhir.api.generic import FHIRReadView, FHIRSearchView


class AuditEventView(FHIRReadView, FHIRSearchView):
    fhir_resource_type = "AuditEvent"
