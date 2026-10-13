"""Capability boundaries shared by the POS clinical and financial read edges.

Tenant scoping is still required in every queryset. Authentication alone is
not permission to browse a tenant's patient or cashier records.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

DISPENSING_READ_CAPABILITIES = (
    "dispensing.read", "dispensing.reserve", "dispensing.allocate",
    "dispensing.prepare", "dispensing.check", "dispensing.counsel",
    "dispensing.supply", "prescriptions.record_payment",
)
CLINICAL_DETAIL_CAPABILITIES = (
    "clinical.read", "prescriptions.clinical_review",
    "prescriptions.pharmacist_verify", "dispensing.check", "dispensing.counsel",
    "pos.clinical_findings.view_detail",
)


def has_any_capability(user, tenant_id, capabilities):
    return bool(tenant_id and user and user.is_authenticated) and any(
        user.has_capability(capability, tenant_id=tenant_id)
        for capability in capabilities
    )


def can_read_clinical_details(request, tenant_id):
    return bool(request) and has_any_capability(
        request.user, tenant_id, CLINICAL_DETAIL_CAPABILITIES
    )


def scope_to_actor_branches(queryset, request, field="branch_id"):
    # Absence means tenant-wide authority as configured by the tenant. An
    # explicitly empty assignment means no branches, not all branches.
    metadata = getattr(request.user, "metadata", None) or {}
    if "branch_ids" in metadata and not request.user.is_superuser:
        return queryset.filter(**{f"{field}__in": metadata["branch_ids"] or []})
    return queryset


class PosReadCapabilityPermission(BasePermission):
    message = "The required POS read capability is not assigned."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Writes have their own authoritative service capability checks. This
        # permission never replaces them or confers write authority.
        if request.method not in SAFE_METHODS and getattr(view, "action", None) not in {"verify_batch", "evaluate"}:
            return True
        tenant_id = getattr(request, "tenant_id", None) or getattr(request.user, "tenant_id", None)
        return has_any_capability(
            request.user, tenant_id, getattr(view, "pos_read_capabilities", ())
        )
