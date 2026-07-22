from django.contrib import admin

from apps.cds.models import ClinicalEvaluation, ClinicalFinding, ClinicalKnowledgeRelease, ClinicalKnowledgeRule

admin.site.register([ClinicalKnowledgeRelease, ClinicalKnowledgeRule, ClinicalEvaluation, ClinicalFinding])
