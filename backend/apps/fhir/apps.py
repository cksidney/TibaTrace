import fhir.resources
import pydantic
from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured

FHIR_RESOURCES_VERSION = "6.5.0"
PYDANTIC_MAJOR_VERSION = "1"


def assert_fhir_r4_runtime() -> None:
    if fhir.resources.__version__ != FHIR_RESOURCES_VERSION:
        raise ImproperlyConfigured(
            f"FHIR R4 requires fhir.resources=={FHIR_RESOURCES_VERSION}; "
            f"found {fhir.resources.__version__}."
        )
    if pydantic.VERSION.split(".", 1)[0] != PYDANTIC_MAJOR_VERSION:
        raise ImproperlyConfigured(
            f"FHIR R4 requires Pydantic major version {PYDANTIC_MAJOR_VERSION}; "
            f"found {pydantic.VERSION}."
        )

    from fhir.resources.medicationrequest import MedicationRequest

    required_fields = {
        "medicationReference",
        "medicationCodeableConcept",
        "subject",
        "requester",
        "dosageInstruction",
        "dispenseRequest",
        "substitution",
        "reasonReference",
        "supportingInformation",
    }
    missing = sorted(required_fields - set(MedicationRequest.__fields__))
    if missing:
        raise ImproperlyConfigured(
            "The installed FHIR model stack is not the approved R4 runtime; "
            f"MedicationRequest fields are missing: {', '.join(missing)}."
        )


class FhirConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.fhir"
    label = "fhir"
    verbose_name = "FHIR Interoperability"

    def ready(self):
        assert_fhir_r4_runtime()

        from apps.fhir.registry_init import init_registry

        init_registry()
