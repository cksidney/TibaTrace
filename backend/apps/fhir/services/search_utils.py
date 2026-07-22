from django.conf import settings

from apps.fhir.exceptions import FHIRValidationError


def bounded_count(params, default: int = 50) -> int:
    raw = params.get("_count", default)
    try:
        requested = int(raw)
    except (TypeError, ValueError) as exc:
        raise FHIRValidationError("_count must be an integer.", expression="_count") from exc
    if requested < 1:
        raise FHIRValidationError("_count must be greater than zero.", expression="_count")
    return min(requested, settings.FHIR_SEARCH_MAX_COUNT)


def reference_id(value, expected_type: str):
    if not value:
        return None
    text = str(value).strip()
    if "/" not in text:
        return text
    resource_type, resource_id = text.split("/", 1)
    if resource_type != expected_type or not resource_id:
        raise FHIRValidationError(
            f"Expected a {expected_type} reference.",
            expression=expected_type.lower(),
        )
    return resource_id
