from django.contrib import admin

from .models import (
    ClaimAdjudication,
    InsuranceCoverage,
    InsuranceMember,
    InsuranceRemittance,
    Insurer,
    InsurerPlan,
    InsurerScheme,
    MedicineClaimCodeMap,
    PrescriptionClaim,
    PrescriptionPreauthorisation,
)

admin.site.register(Insurer)
admin.site.register(InsurerScheme)
admin.site.register(InsurerPlan)
admin.site.register(InsuranceMember)
admin.site.register(InsuranceCoverage)
admin.site.register(PrescriptionPreauthorisation)
admin.site.register(PrescriptionClaim)
admin.site.register(ClaimAdjudication)
admin.site.register(InsuranceRemittance)
admin.site.register(MedicineClaimCodeMap)
