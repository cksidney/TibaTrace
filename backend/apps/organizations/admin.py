from django.contrib import admin

from apps.organizations.models import Location, Organization, OrganizationIdentifier

admin.site.register([Organization, OrganizationIdentifier, Location])
