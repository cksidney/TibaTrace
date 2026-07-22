from django.contrib import admin

from apps.clinical.models import (
    ClinicalCondition,
    ClinicalDiagnosticReport,
    ClinicalDocument,
    ClinicalEncounter,
    ClinicalObservation,
    MedicationAdministrationRecord,
)

admin.site.register([
    ClinicalEncounter,
    ClinicalCondition,
    ClinicalObservation,
    ClinicalDiagnosticReport,
    ClinicalDocument,
    MedicationAdministrationRecord,
])
