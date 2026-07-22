from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from fhir.resources.parameters import Parameters

from apps.fhir.exceptions import FHIRValidationError

VALUE_FIELDS = (
    "valueUri",
    "valueCanonical",
    "valueUrl",
    "valueCode",
    "valueString",
    "valueBoolean",
    "valueInteger",
    "valueDate",
    "valueDateTime",
    "valueCoding",
    "valueCodeableConcept",
    "valueIdentifier",
)


def parameter_values(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "getlist"):
        return {
            key: values[-1]
            for key in payload.keys()
            if (values := payload.getlist(key))
        }
    if isinstance(payload, dict) and payload.get("resourceType") != "Parameters":
        return dict(payload)
    parameters = Parameters.parse_obj(payload)
    values = {}
    for parameter in parameters.parameter or []:
        if parameter.resource is not None:
            values[parameter.name] = parameter.resource
            continue
        for field_name in VALUE_FIELDS:
            value = getattr(parameter, field_name, None)
            if value is not None:
                values[parameter.name] = value
                break
    return values


def coding_values(values: dict[str, Any]) -> tuple[str, str, str, str]:
    system = str(values.get("system") or "")
    code = str(values.get("code") or "")
    version = str(values.get("systemVersion") or values.get("version") or "")
    display = str(values.get("display") or "")
    coding = values.get("coding")
    concept = values.get("codeableConcept")
    if concept is not None:
        codings = getattr(concept, "coding", None) or (
            concept.get("coding", []) if isinstance(concept, dict) else []
        )
        coding = codings[0] if codings else coding
    if coding is not None:
        getter = coding.get if isinstance(coding, dict) else lambda key, default=None: getattr(coding, key, default)
        system = str(getter("system") or system)
        code = str(getter("code") or code)
        version = str(getter("version") or version)
        display = str(getter("display") or display)
    return system, code, version, display


def boolean_value(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise FHIRValidationError("Boolean terminology parameter is invalid.")


def terminology_as_of(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        raw = str(value).strip()
        parsed = parse_datetime(raw)
        if parsed is None:
            parsed_date = parse_date(raw)
            parsed = datetime.combine(parsed_date, time.min) if parsed_date else None
    if parsed is None:
        raise FHIRValidationError("date must be a valid FHIR date or dateTime.")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def parameters_result(
    *,
    result: bool,
    message: str = "",
    display: str = "",
    code: str = "",
    system: str = "",
    version: str = "",
) -> dict[str, Any]:
    parameters = [{"name": "result", "valueBoolean": result}]
    for name, field, value in (
        ("message", "valueString", message),
        ("display", "valueString", display),
        ("code", "valueCode", code),
        ("system", "valueUri", system),
        ("version", "valueString", version),
    ):
        if value:
            parameters.append({"name": name, field: value})
    return {"resourceType": "Parameters", "parameter": parameters}
