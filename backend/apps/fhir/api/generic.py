from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.fhir.api.base import BaseFHIRAPIView
from apps.fhir.api.permissions import FHIRResourcePermission
from apps.fhir.exceptions import (
    FHIRNotSupportedError,
    FHIRReferenceResolutionError,
    FHIRSecurityError,
    FHIRValidationError,
)
from apps.fhir.services.resource_registry import FHIRResourceRegistry


class FHIRReadView(BaseFHIRAPIView):
    """Generic view to handle FHIR read (GET by ID) operations."""

    permission_classes = [FHIRResourcePermission]

    def get(self, request, *args, **kwargs):
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            raise FHIRSecurityError("Missing tenant context.")

        resource_type = self.fhir_resource_type
        resource_id = kwargs.get('id')

        if resource_id is None:
            return FHIRSearchView.get(self, request, *args, **kwargs)

        registration = FHIRResourceRegistry.get_registration(resource_type)
        if not registration.interactions.read:
            raise FHIRNotSupportedError(f"Read operation not supported for {resource_type}")

        service = registration.service_class
        converter = registration.converter_class()

        domain_instance = service.get_by_id(resource_id, tenant_id)
        if not domain_instance:
            raise FHIRReferenceResolutionError(
                f"{resource_type} is unavailable in the active tenant.", code="not-found"
            )

        conversion_result = converter.to_fhir(domain_instance, {"tenant_id": tenant_id})
        if conversion_result.errors or not conversion_result.fhir_resource:
            raise FHIRValidationError(
                "The domain record could not be rendered as FHIR.",
                diagnostics="; ".join(conversion_result.errors) or "No FHIR resource was produced.",
            )
        return Response(conversion_result.fhir_resource.dict(exclude_none=True))


class FHIRSearchView(BaseFHIRAPIView):
    """Generic view to handle FHIR search (GET) operations returning searchset bundles."""

    permission_classes = [FHIRResourcePermission]

    def get(self, request, *args, **kwargs):
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            raise FHIRSecurityError("Missing tenant context.")

        resource_type = self.fhir_resource_type
        registration = FHIRResourceRegistry.get_registration(resource_type)
        if not registration.interactions.search:
            raise FHIRNotSupportedError(f"Search operation not supported for {resource_type}")

        allowed_parameters = set(registration.search_parameters) | {"_count", "_format", "_pretty"}
        unsupported = sorted(set(request.query_params.keys()) - allowed_parameters)
        if unsupported:
            raise FHIRValidationError(
                "Unsupported search parameter.",
                diagnostics=f"Unsupported parameters: {', '.join(unsupported)}",
            )

        service = registration.service_class
        converter = registration.converter_class()

        # For Checkpoint 5, we provide a simplified search implementation.
        # A real implementation would parse query params and filter.
        # Here we attempt to fetch a subset (or empty list if the service doesn't support generic list)

        # We need the service to have a `search` method, if it doesn't, we return empty bundle
        domain_instances = []
        if hasattr(service, 'search'):
            domain_instances = service.search(request.query_params, tenant_id)

        import fhir.resources.bundle as fhir_bundle

        bundle = fhir_bundle.Bundle(
            type="searchset",
            total=len(domain_instances),
            entry=[]
        )

        for instance in domain_instances:
            conversion_result = converter.to_fhir(instance, {"tenant_id": tenant_id})
            if conversion_result.errors or not conversion_result.fhir_resource:
                raise FHIRValidationError(
                    "A search result could not be rendered as FHIR.",
                    diagnostics="; ".join(conversion_result.errors) or "No FHIR resource was produced.",
                )
            entry = fhir_bundle.BundleEntry(
                fullUrl=request.build_absolute_uri(f"/api/fhir/r4/{resource_type}/{instance.id}"),
                resource=conversion_result.fhir_resource
            )
            bundle.entry.append(entry)

        return Response(bundle.dict(exclude_none=True))
