from django.contrib import admin

from apps.prescription.models import Prescription, PrescriptionDispense, PrescriptionFill, PrescriptionItem

admin.site.register([Prescription, PrescriptionItem, PrescriptionDispense, PrescriptionFill])
