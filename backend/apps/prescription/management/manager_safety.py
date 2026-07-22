from __future__ import annotations

from django.apps import apps

from apps.cds.models import ClinicalKnowledgeManager
from apps.core.models import StrictTenantManager
from apps.identity.models import DawaTraceUserManager, User
from apps.terminology.models import TerminologyManager

APPROVED_TENANT_MANAGERS = (StrictTenantManager, ClinicalKnowledgeManager, TerminologyManager)


def audit_tenant_managers() -> dict:
    models = []
    findings = []
    exceptions = []
    for model in apps.get_models():
        if not any(field.name == "tenant" for field in model._meta.fields):
            continue
        manager = model._default_manager
        row = {"model": model._meta.label, "manager": type(manager).__name__}
        models.append(row)
        if model is User and isinstance(manager, DawaTraceUserManager):
            exceptions.append(
                {
                    **row,
                    "reason": "Authentication resolves users before tenant middleware; authorization remains tenant-qualified.",
                }
            )
            continue
        if not isinstance(manager, APPROVED_TENANT_MANAGERS):
            findings.append(row)
    return {
        "model_count": len(models),
        "models": models,
        "approved_exception_count": len(exceptions),
        "approved_exceptions": exceptions,
        "finding_count": len(findings),
        "findings": findings,
    }
