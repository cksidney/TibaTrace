from typing import Any, Dict

from fhir.resources.contactpoint import ContactPoint
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.patient import Patient as FHIRPatient

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.fhir.kenya_hie import (
    SYSTEM_CLIENT_REGISTRY_ID,
    SYSTEM_LOCAL_PATIENT_REFERENCE,
    extract_client_registry_id,
)
from apps.patients.models import Patient


class PatientConverter(BaseFHIRConverter):
    resource_type = "Patient"

    def to_fhir(self, domain_object: Patient, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            identifiers = [Identifier(system=row.system, value=row.value) for row in domain_object.identifiers.all()]
            identifiers.insert(
                0,
                Identifier(
                    system=SYSTEM_LOCAL_PATIENT_REFERENCE,
                    value=domain_object.internal_reference_id,
                ),
            )
            cr_id = extract_client_registry_id(domain_object)
            if cr_id and not any(
                (getattr(i, "system", None) or "") == SYSTEM_CLIENT_REGISTRY_ID for i in identifiers
            ):
                identifiers.append(Identifier(system=SYSTEM_CLIENT_REGISTRY_ID, value=cr_id))

            telecom = []
            if domain_object.phone:
                telecom.append(ContactPoint(system="phone", value=domain_object.phone))
            if domain_object.email:
                telecom.append(ContactPoint(system="email", value=domain_object.email))
            result.fhir_resource = FHIRPatient(
                id=str(domain_object.id),
                identifier=identifiers,
                active=domain_object.is_active,
                name=[
                    HumanName(
                        family=domain_object.last_name or None,
                        given=[domain_object.first_name] if domain_object.first_name else None,
                        text=domain_object.full_name or None,
                    )
                ],
                telecom=telecom or None,
                gender=domain_object.sex.lower(),
                birthDate=domain_object.date_of_birth,
            )
        except Exception:
            result.add_exception("Patient could not be rendered as FHIR Patient.")
        return result

    def to_domain_command(self, resource: FHIRPatient, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            identifiers = [
                {"system": identifier.system or "", "value": identifier.value or ""}
                for identifier in resource.identifier or []
                if identifier.value
            ]
            reference = next(
                (
                    row["value"]
                    for row in identifiers
                    if row["system"] == SYSTEM_LOCAL_PATIENT_REFERENCE
                ),
                None,
            )
            name = (resource.name or [None])[0]
            telecom = {row.system: row.value for row in resource.telecom or [] if row.system and row.value}
            result.domain_command = {
                "id": resource.id,
                "internal_reference_id": reference or str(resource.id or ""),
                "verification_status": "VERIFIED" if resource.active is not False else "ENTERED_IN_ERROR",
                "first_name": (name.given or [""])[0] if name else "",
                "last_name": name.family or "" if name else "",
                "date_of_birth": resource.birthDate,
                "sex": (resource.gender or "unknown").upper(),
                "phone": telecom.get("phone", ""),
                "email": telecom.get("email", ""),
                "is_active": resource.active is not False,
                "identifiers": [
                    row
                    for row in identifiers
                    if row["system"] != SYSTEM_LOCAL_PATIENT_REFERENCE
                ],
            }
        except Exception:
            result.add_exception("FHIR Patient could not be mapped to a DawaTrace patient command.")
        return result
