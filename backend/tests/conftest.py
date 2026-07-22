from __future__ import annotations

import pytest
from django.utils import timezone

from apps.identity.models import Role, User, UserRole
from apps.medicines.models import Medicine
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient
from apps.practitioners.models import Practitioner, PractitionerLicence, PractitionerRole
from apps.tenancy.models import Tenant

ALL_CAPABILITIES = [
    "organizations.read", "organizations.write", "patients.read", "patients.write",
    "practitioners.read", "practitioners.write", "prescriptions.read", "prescriptions.write",
    "prescriptions.review", "prescriptions.approve", "prescriptions.record_payment",
    "dispensing.read", "dispensing.prepare", "dispensing.complete", "dispensing.reverse", "dispensing.substitute",
    "clinical.read", "clinical.write", "cds.read", "cds.configure.read", "cds.configure", "cds.override",
    "terminology.read", "terminology.manage", "audit.read", "documents.read", "documents.write",
    "system/Organization.read", "system/Location.read", "system/Patient.read", "system/Patient.write",
    "system/Practitioner.read", "system/Medication.read", "system/MedicationRequest.read",
    "system/MedicationRequest.write", "system/MedicationDispense.read", "system/MedicationDispense.write",
    "system/MedicationStatement.read", "system/AuditEvent.read", "system/AllergyIntolerance.read",
    "system/AllergyIntolerance.write", "system/Condition.read", "system/Condition.write",
    "system/Encounter.read", "system/Encounter.write", "system/MedicationAdministration.read",
    "system/MedicationAdministration.write", "system/Observation.read", "system/Observation.write",
    "system/DiagnosticReport.read", "system/DiagnosticReport.write", "system/DocumentReference.read",
    "system/DocumentReference.write", "system/CodeSystem.read", "system/ValueSet.read",
    "system/Terminology.validate", "system/Terminology.expand",
]


@pytest.fixture
def tenant_a(db):
    return Tenant.objects.create(name="Tenant A Pharmacy", slug="tenant-a")


@pytest.fixture
def tenant_b(db):
    return Tenant.objects.create(name="Tenant B Pharmacy", slug="tenant-b")


@pytest.fixture
def clinical_setup(tenant_a):
    organization = Organization.all_objects.create(
        tenant=tenant_a, name="DawaTrace Demo Pharmacy", code="DTP", organization_type="PHARMACY"
    )
    location = Location.all_objects.create(
        tenant=tenant_a, organization=organization, name="Main Dispensary", code="MAIN"
    )
    patient = Patient.all_objects.create(
        tenant=tenant_a,
        internal_reference_id="PAT-001",
        verification_status="VERIFIED",
        first_name="Amina",
        last_name="Kamau",
        date_of_birth="1990-01-02",
        sex="FEMALE",
    )
    practitioner = Practitioner.all_objects.create(
        tenant=tenant_a, first_name="David", last_name="Otieno", status="ACTIVE"
    )
    PractitionerLicence.all_objects.create(
        tenant=tenant_a,
        practitioner=practitioner,
        licence_number="PPB-1001",
        issuer="PPB",
        status="VALID",
    )
    PractitionerRole.all_objects.create(
        tenant=tenant_a,
        practitioner=practitioner,
        organization=organization,
        location=location,
        role_code="PHARMACIST",
        status="ACTIVE",
    )
    medicine_a = Medicine.all_objects.create(
        tenant=tenant_a,
        code="MED-A",
        generic_name="Demo medicine A",
        dosage_form="tablet",
        status="ACTIVE",
        source="DawaTrace test fixture",
        source_version="1",
    )
    medicine_b = Medicine.all_objects.create(
        tenant=tenant_a,
        code="MED-B",
        generic_name="Demo medicine B",
        dosage_form="tablet",
        status="ACTIVE",
        source="DawaTrace test fixture",
        source_version="1",
    )
    return {
        "tenant": tenant_a,
        "organization": organization,
        "location": location,
        "patient": patient,
        "practitioner": practitioner,
        "medicine_a": medicine_a,
        "medicine_b": medicine_b,
        "now": timezone.now(),
    }


@pytest.fixture
def clinical_user(tenant_a):
    user = User.objects.create_user(
        username="clinical-admin",
        email="clinical@example.test",
        password="test-password-strong",
        tenant=tenant_a,
    )
    role = Role.all_objects.create(
        tenant=tenant_a, code="CLINICAL_ADMIN", name="Clinical administrator", capabilities=ALL_CAPABILITIES
    )
    UserRole.all_objects.create(tenant=tenant_a, user=user, role=role)
    return user


@pytest.fixture
def cashier_user(tenant_a):
    user = User.objects.create_user(
        username="cashier", email="cashier@example.test", password="test-password-strong", tenant=tenant_a
    )
    role = Role.all_objects.create(
        tenant=tenant_a,
        code="CASHIER",
        name="Cashier",
        capabilities=["patients.read", "prescriptions.read", "dispensing.read"],
    )
    UserRole.all_objects.create(tenant=tenant_a, user=user, role=role)
    return user
