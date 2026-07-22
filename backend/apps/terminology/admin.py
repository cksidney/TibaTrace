from django.contrib import admin

from apps.terminology.models import FHIRCodeSystemRegistration, FHIRTerminologyVersion, FHIRValueSetRegistration

admin.site.register([FHIRTerminologyVersion, FHIRCodeSystemRegistration, FHIRValueSetRegistration])
