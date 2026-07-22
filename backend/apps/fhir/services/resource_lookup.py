from __future__ import annotations

import uuid

from django.db import transaction
from django.db.models import Q

from apps.fhir.services.search_utils import bounded_count, reference_id
from apps.organizations.models import Location, LocationIdentifier, Organization, OrganizationIdentifier
from apps.patients.models import Patient, PatientIdentifier
from apps.practitioners.models import Practitioner, PractitionerIdentifier, PractitionerRole


def _token(value: str) -> tuple[str, str]:
    system, separator, identifier = str(value or "").partition("|")
    return (system, identifier) if separator else ("", system)


class OrganizationLookupService:
    @staticmethod
    def get_by_id(resource_id, tenant_id):
        return Organization.all_objects.filter(id=resource_id, tenant_id=tenant_id).first()

    @staticmethod
    def get_by_identifier(system, value, tenant_id):
        row = OrganizationIdentifier.all_objects.select_related("organization").filter(
            tenant_id=tenant_id, system=system, value=value, organization__tenant_id=tenant_id
        ).first()
        return row.organization if row else None

    @staticmethod
    def search(params, tenant_id):
        queryset = Organization.all_objects.filter(tenant_id=tenant_id)
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("name"):
            queryset = queryset.filter(name__icontains=params["name"])
        if params.get("active"):
            queryset = queryset.filter(status="ACTIVE" if str(params["active"]).lower() == "true" else "INACTIVE")
        if params.get("identifier"):
            system, value = _token(params["identifier"])
            identifiers = OrganizationIdentifier.all_objects.filter(tenant_id=tenant_id, value=value)
            if system:
                identifiers = identifiers.filter(system=system)
            queryset = queryset.filter(id__in=identifiers.values("organization_id"))
        return list(queryset.order_by("name", "id")[: bounded_count(params)])


class LocationLookupService:
    @staticmethod
    def get_by_id(resource_id, tenant_id):
        return Location.all_objects.filter(id=resource_id, tenant_id=tenant_id).first()

    @staticmethod
    def search(params, tenant_id):
        queryset = Location.all_objects.filter(tenant_id=tenant_id)
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("identifier"):
            system, value = _token(params["identifier"])
            identifiers = LocationIdentifier.all_objects.filter(tenant_id=tenant_id, value=value)
            if system:
                identifiers = identifiers.filter(system=system)
            queryset = queryset.filter(id__in=identifiers.values("location_id"))
        if params.get("name"):
            queryset = queryset.filter(name__icontains=params["name"])
        if params.get("organization"):
            queryset = queryset.filter(organization_id=reference_id(params["organization"], "Organization"))
        if params.get("status"):
            queryset = queryset.filter(status="ACTIVE" if str(params["status"]).lower() == "active" else "INACTIVE")
        return list(queryset.order_by("name", "id")[: bounded_count(params)])


class PatientLookupService:
    @staticmethod
    def get_by_id(resource_id, tenant_id):
        return Patient.all_objects.filter(id=resource_id, tenant_id=tenant_id).first()

    @staticmethod
    def get_by_identifier(system, value, tenant_id):
        row = PatientIdentifier.all_objects.select_related("patient").filter(
            tenant_id=tenant_id, system=system, value=value, patient__tenant_id=tenant_id
        ).first()
        if row:
            return row.patient
        return Patient.all_objects.filter(tenant_id=tenant_id, internal_reference_id=value).first()

    @staticmethod
    def search(params, tenant_id):
        queryset = Patient.all_objects.filter(tenant_id=tenant_id)
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("identifier"):
            system, value = _token(params["identifier"])
            identifiers = PatientIdentifier.all_objects.filter(tenant_id=tenant_id, value=value)
            if system:
                identifiers = identifiers.filter(system=system)
            queryset = queryset.filter(Q(internal_reference_id=value) | Q(id__in=identifiers.values("patient_id")))
        if params.get("name"):
            queryset = queryset.filter(Q(first_name__icontains=params["name"]) | Q(last_name__icontains=params["name"]))
        if params.get("birthdate"):
            queryset = queryset.filter(date_of_birth=params["birthdate"])
        if params.get("active"):
            queryset = queryset.filter(is_active=str(params["active"]).lower() == "true")
        return list(queryset.order_by("last_name", "first_name", "id")[: bounded_count(params)])

    @staticmethod
    @transaction.atomic
    def process_domain_command(domain_command, context):
        tenant_id = context.get("tenant_id")
        if not tenant_id:
            raise ValueError("Tenant ID is missing in context.")
        resource_id = domain_command.get("id")
        patient = Patient.all_objects.select_for_update().filter(id=resource_id, tenant_id=tenant_id).first() if resource_id else None
        if resource_id and not patient and context.get("operation") == "update":
            raise ValueError("Patient is unavailable in the active tenant.")
        if not patient:
            patient = Patient(id=uuid.UUID(str(resource_id)) if resource_id else uuid.uuid4(), tenant_id=tenant_id)
        for field in (
            "internal_reference_id", "verification_status", "first_name", "last_name", "date_of_birth", "sex",
            "phone", "email", "is_active",
        ):
            if field in domain_command:
                setattr(patient, field, domain_command[field])
        patient.full_clean()
        patient.save()
        if "identifiers" in domain_command:
            PatientIdentifier.all_objects.filter(tenant_id=tenant_id, patient=patient).delete()
            for identifier in domain_command["identifiers"]:
                PatientIdentifier.all_objects.create(
                    tenant_id=tenant_id, patient=patient, system=identifier["system"], value=identifier["value"]
                )
        return patient


class PractitionerLookupService:
    @staticmethod
    def get_by_id(resource_id, tenant_id):
        return Practitioner.all_objects.filter(id=resource_id, tenant_id=tenant_id).first()

    @staticmethod
    def get_by_identifier(system, value, tenant_id):
        row = PractitionerIdentifier.all_objects.select_related("practitioner").filter(
            tenant_id=tenant_id, system=system, value=value, practitioner__tenant_id=tenant_id
        ).first()
        return row.practitioner if row else None

    @staticmethod
    def search(params, tenant_id):
        queryset = Practitioner.all_objects.filter(tenant_id=tenant_id)
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("identifier"):
            system, value = _token(params["identifier"])
            identifiers = PractitionerIdentifier.all_objects.filter(tenant_id=tenant_id, value=value)
            if system:
                identifiers = identifiers.filter(system=system)
            queryset = queryset.filter(id__in=identifiers.values("practitioner_id"))
        if params.get("name"):
            queryset = queryset.filter(Q(first_name__icontains=params["name"]) | Q(last_name__icontains=params["name"]))
        if params.get("active"):
            queryset = queryset.filter(status="ACTIVE" if str(params["active"]).lower() == "true" else "INACTIVE")
        return list(queryset.order_by("last_name", "first_name", "id")[: bounded_count(params)])


class PractitionerRoleLookupService:
    @staticmethod
    def get_by_id(resource_id, tenant_id):
        return PractitionerRole.all_objects.filter(id=resource_id, tenant_id=tenant_id).first()

    @staticmethod
    def search(params, tenant_id):
        queryset = PractitionerRole.all_objects.filter(tenant_id=tenant_id)
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("practitioner"):
            queryset = queryset.filter(practitioner_id=reference_id(params["practitioner"], "Practitioner"))
        if params.get("organization"):
            queryset = queryset.filter(organization_id=reference_id(params["organization"], "Organization"))
        if params.get("location"):
            queryset = queryset.filter(location_id=reference_id(params["location"], "Location"))
        return list(queryset.order_by("id")[: bounded_count(params)])
