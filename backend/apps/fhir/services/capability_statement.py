from datetime import datetime, timezone

from django.conf import settings
from fhir.resources.capabilitystatement import (
    CapabilityStatement,
    CapabilityStatementImplementation,
    CapabilityStatementRest,
    CapabilityStatementRestResource,
    CapabilityStatementRestResourceInteraction,
    CapabilityStatementRestResourceSearchParam,
    CapabilityStatementSoftware,
)

from apps.fhir.constants import FHIR_VERSION
from apps.fhir.services.resource_registry import FHIRResourceRegistry


class CapabilityStatementService:
    """Service to generate the FHIR CapabilityStatement based on the resource registry."""

    @classmethod
    def generate(cls, request=None) -> CapabilityStatement:
        # Build REST resources dynamically from registry
        rest_resources = []
        for reg in FHIRResourceRegistry.all_registrations():
            interactions = []
            if reg.interactions.read:
                interactions.append(CapabilityStatementRestResourceInteraction(code="read"))
            service_supports_writes = callable(getattr(reg.service_class, "process_domain_command", None))
            writes_enabled = settings.FHIR_WRITE_INTERACTIONS_ENABLED and service_supports_writes
            if reg.interactions.create and writes_enabled:
                interactions.append(CapabilityStatementRestResourceInteraction(code="create"))
            if reg.interactions.update and writes_enabled:
                interactions.append(CapabilityStatementRestResourceInteraction(code="update"))
            if reg.interactions.search:
                interactions.append(CapabilityStatementRestResourceInteraction(code="search-type"))

            search_params = []
            for param in reg.search_parameters:
                # Basic representation, ideally type should be derived from definition
                search_params.append(
                    CapabilityStatementRestResourceSearchParam(
                        name=param,
                        type="string"  # Simplified for initial implementation
                    )
                )

            rest_resource = CapabilityStatementRestResource(
                type=reg.resource_type,
                interaction=interactions if interactions else None,
                searchParam=search_params if search_params else None,
                supportedProfile=reg.supported_profiles if reg.supported_profiles else None
            )
            rest_resources.append(rest_resource)

        from fhir.resources.capabilitystatement import CapabilityStatementRestInteraction

        system_interactions = []
        if settings.FHIR_WRITE_INTERACTIONS_ENABLED:
            system_interactions = [
                CapabilityStatementRestInteraction(code="batch"),
                CapabilityStatementRestInteraction(code="transaction"),
            ]

        rest = CapabilityStatementRest(
            mode="server",
            resource=rest_resources if rest_resources else None,
            interaction=system_interactions or None,
        )

        base_url = settings.FHIR_PUBLIC_BASE_URL
        if request:
            base_url = request.build_absolute_uri("/api/fhir/r4/")

        statement = CapabilityStatement(
            status="active",
            date=datetime.now(timezone.utc).isoformat(),
            publisher="Esenai Group Ltd",
            kind="instance",
            software=CapabilityStatementSoftware(
                name="DawaTrace FHIR Gateway",
                version="0.1.0-alpha.1"
            ),
            implementation=CapabilityStatementImplementation(
                description="DawaTrace FHIR R4 Interoperability Foundation",
                url=base_url
            ),
            fhirVersion=FHIR_VERSION,
            format=["application/fhir+json"],
            rest=[rest]
        )

        return statement
