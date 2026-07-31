from datetime import datetime, timezone

from django.conf import settings
from fhir.resources.capabilitystatement import (
    CapabilityStatement,
    CapabilityStatementImplementation,
    CapabilityStatementRest,
    CapabilityStatementRestResource,
    CapabilityStatementRestResourceInteraction,
    CapabilityStatementRestResourceSearchParam,
    CapabilityStatementRestSecurity,
    CapabilityStatementSoftware,
)
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.extension import Extension

from apps.fhir.constants import FHIR_VERSION
from apps.fhir.kenya_claims_ig import KENYA_CLAIMS_IG_HOME, KENYA_CLAIMS_IG_NAME, KENYA_CLAIMS_IG_VERSION
from apps.fhir.kenya_ig import KENYA_ERX_IG_HOME, KENYA_ERX_IG_NAME, KENYA_ERX_IG_VERSION
from apps.fhir.services.resource_registry import FHIRResourceRegistry


class CapabilityStatementService:
    """Service to generate the FHIR CapabilityStatement based on the resource registry."""

    @classmethod
    def generate(cls, request=None) -> CapabilityStatement:
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

            search_params = [
                CapabilityStatementRestResourceSearchParam(name=param.name, type=param.type)
                for param in reg.search_parameter_specs()
            ]

            rest_resource = CapabilityStatementRestResource(
                type=reg.resource_type,
                interaction=interactions if interactions else None,
                searchParam=search_params if search_params else None,
                supportedProfile=reg.supported_profiles if reg.supported_profiles else None,
            )
            rest_resources.append(rest_resource)

        from fhir.resources.capabilitystatement import CapabilityStatementRestInteraction

        system_interactions = []
        if settings.FHIR_WRITE_INTERACTIONS_ENABLED:
            system_interactions = [
                CapabilityStatementRestInteraction(code="batch"),
                CapabilityStatementRestInteraction(code="transaction"),
            ]

        base_url = settings.FHIR_PUBLIC_BASE_URL
        if request:
            base_url = request.build_absolute_uri("/api/fhir/r4/")
        if not base_url.endswith("/"):
            base_url = base_url + "/"

        smart_config_url = getattr(
            settings,
            "FHIR_SMART_CONFIGURATION_URL",
            base_url.rstrip("/") + "/.well-known/smart-configuration",
        )
        oauth_authorize = getattr(settings, "FHIR_SMART_AUTHORIZATION_ENDPOINT", "") or ""
        oauth_token = getattr(settings, "FHIR_SMART_TOKEN_ENDPOINT", "") or ""

        oauth_extensions = []
        if oauth_authorize:
            oauth_extensions.append(Extension(url="authorize", valueUri=oauth_authorize))
        if oauth_token:
            oauth_extensions.append(Extension(url="token", valueUri=oauth_token))

        security_kwargs = {
            "cors": True,
            "service": [
                CodeableConcept(
                    coding=[
                        Coding(
                            system="http://hl7.org/fhir/restful-security-service",
                            code="SMART-on-FHIR",
                            display="SMART-on-FHIR",
                        )
                    ],
                    text="OAuth2 using SMART-on-FHIR profile (see SMART configuration)",
                )
            ],
            "description": (
                f"SMART on FHIR / OAuth 2.x (AfyaLink Bearer JWT). "
                f"Clinical IG: {KENYA_ERX_IG_NAME} {KENYA_ERX_IG_VERSION}. "
                f"Claims/preauth: {KENYA_CLAIMS_IG_NAME} {KENYA_CLAIMS_IG_VERSION}. "
                f"Discovery: {smart_config_url}"
            ),
        }
        if oauth_extensions:
            security_kwargs["extension"] = [
                Extension(
                    url="http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris",
                    extension=oauth_extensions,
                )
            ]
        security = CapabilityStatementRestSecurity(**security_kwargs)

        rest = CapabilityStatementRest(
            mode="server",
            security=security,
            resource=rest_resources if rest_resources else None,
            interaction=system_interactions or None,
        )

        return CapabilityStatement(
            status="active",
            date=datetime.now(timezone.utc).isoformat(),
            publisher="Esenai Group Ltd",
            kind="instance",
            instantiates=[KENYA_ERX_IG_HOME, KENYA_CLAIMS_IG_HOME],
            software=CapabilityStatementSoftware(
                name="DawaTrace FHIR Gateway",
                version="0.1.0-alpha.1",
            ),
            implementation=CapabilityStatementImplementation(
                description=(
                    f"DawaTrace FHIR R4 gateway — clinical: {KENYA_ERX_IG_NAME} "
                    f"{KENYA_ERX_IG_VERSION}; reimbursement: {KENYA_CLAIMS_IG_NAME} "
                    f"{KENYA_CLAIMS_IG_VERSION}; Content-Type application/fhir+json; currency KES"
                ),
                url=base_url,
            ),
            fhirVersion=FHIR_VERSION,
            format=["application/fhir+json"],
            rest=[rest],
        )
