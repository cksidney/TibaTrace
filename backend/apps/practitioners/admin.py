from django.contrib import admin

from apps.practitioners.models import Practitioner, PractitionerIdentifier, PractitionerLicence, PractitionerRole

admin.site.register([Practitioner, PractitionerIdentifier, PractitionerLicence, PractitionerRole])
