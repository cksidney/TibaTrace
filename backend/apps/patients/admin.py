from django.contrib import admin

from apps.patients.models import Patient, PatientAllergy, PatientIdentifier, PatientMedication

admin.site.register([Patient, PatientIdentifier, PatientAllergy, PatientMedication])
