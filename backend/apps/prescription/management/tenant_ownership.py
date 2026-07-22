from __future__ import annotations

from django.apps import apps

MODEL_LABELS = (
    "patients.Patient",
    "practitioners.Practitioner",
    "organizations.Organization",
    "organizations.Location",
    "prescription.Prescription",
    "prescription.PrescriptionItem",
    "prescription.PrescriptionDispense",
    "prescription.PrescriptionFill",
    "clinical.ClinicalEncounter",
    "clinical.ClinicalCondition",
    "clinical.ClinicalObservation",
    "clinical.ClinicalDiagnosticReport",
    "clinical.ClinicalDocument",
    "clinical.MedicationAdministrationRecord",
    "cds.ClinicalEvaluation",
    "fhir.FHIRIdempotencyRecord",
)


def audit_ownership(limit: int = 20) -> dict:
    result = {"models": {}, "mismatches": {}, "safe_to_enforce": True}
    for label in MODEL_LABELS:
        model = apps.get_model(label)
        missing = model.all_objects.filter(tenant__isnull=True).count()
        row = {
            "status": "pass" if missing == 0 else "fail",
            "missing_tenant_count": missing,
            "affected_ids": [str(value) for value in model.all_objects.filter(tenant__isnull=True).values_list("id", flat=True)[:limit]],
        }
        result["models"][label] = row
        result["safe_to_enforce"] = result["safe_to_enforce"] and row["status"] == "pass"
    return result
