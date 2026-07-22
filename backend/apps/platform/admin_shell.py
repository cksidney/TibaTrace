from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.cds.models import ClinicalKnowledgeRelease
from apps.clinical.models import ClinicalCondition, ClinicalEncounter, ClinicalObservation
from apps.fhir.models import FHIRIdempotencyRecord
from apps.patients.models import Patient
from apps.practitioners.models import Practitioner
from apps.prescription.models import Prescription
from apps.terminology.models import FHIRCodeSystemRegistration, FHIRValueSetRegistration


@login_required
def admin_shell(request):
    tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
    counts = {}
    if tenant_id:
        counts = {
            "Patients": Patient.all_objects.filter(tenant_id=tenant_id).count(),
            "Practitioners": Practitioner.all_objects.filter(tenant_id=tenant_id).count(),
            "Prescriptions": Prescription.all_objects.filter(tenant_id=tenant_id).count(),
            "Encounters": ClinicalEncounter.all_objects.filter(tenant_id=tenant_id).count(),
            "Conditions": ClinicalCondition.all_objects.filter(tenant_id=tenant_id).count(),
            "Observations": ClinicalObservation.all_objects.filter(tenant_id=tenant_id).count(),
            "CDS releases": ClinicalKnowledgeRelease.all_objects.filter(tenant_id=tenant_id).count(),
            "Code systems": FHIRCodeSystemRegistration.all_objects.filter(tenant_id=tenant_id).count(),
            "Value sets": FHIRValueSetRegistration.all_objects.filter(tenant_id=tenant_id).count(),
            "FHIR idempotency records": FHIRIdempotencyRecord.all_objects.filter(tenant_id=tenant_id).count(),
        }
    return render(request, "platform/admin_shell.html", {"counts": counts, "tenant_id": tenant_id})
