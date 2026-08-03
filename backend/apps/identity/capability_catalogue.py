"""Curated capability catalogue for role governance UI.

Capabilities remain free-form strings on Role.capabilities; this catalogue is a
presentation and discovery aid so operators can grant known authorities without
typing opaque strings. Anything already assigned on a tenant role is always
included even if it is not in the curated list.
"""
from __future__ import annotations

from apps.identity.models import Role

CAPABILITY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Identity & access",
        (
            "identity.manage",
        ),
    ),
    (
        "Platform governance",
        (
            # Designating a demo tenant, and approving a demo seed against one,
            # are Platform Owner acts: they permit fabricated trading history to
            # be written into a real tenant.
            "platform.demo.govern",
        ),
    ),
    (
        "Inventory",
        (
            "inventory.read",
            "inventory.manage",
        ),
    ),
    (
        "Procurement & quality",
        (
            "procurement.read",
            "procurement.write",
            "procurement.approve",
            "quality.release",
        ),
    ),
    (
        "Pricing",
        (
            "pricing.read",
            "pricing.manage",
            "pricing.price_book.manage",
            "pricing.price_book.approve",
            "pricing.price_book.publish",
            "pricing.manual_override.request",
            "pricing.manual_override.approve",
            "pricing.manual_override.approve_below_floor",
        ),
    ),
    (
        "Insurance",
        (
            "insurance.read",
            "insurance.manage",
        ),
    ),
    (
        "Prescriptions & clinical",
        (
            "prescriptions.read",
            "prescriptions.write",
            "prescriptions.intake",
            "prescriptions.legal_validate",
            "prescriptions.clinical_review",
            "prescriptions.pharmacist_verify",
            "prescriptions.review",
            "patients.identity.manage",
            "cds.read",
            "dispensing.read",
        ),
    ),
    (
        "Point of sale",
        (
            "pos.payment.collect",
            "pos.shift.manage",
        ),
    ),
)


def curated_capabilities() -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for _, capabilities in CAPABILITY_GROUPS:
        for capability in capabilities:
            if capability in seen:
                continue
            seen.add(capability)
            ordered.append(capability)
    return ordered


def catalogue_for_tenant(tenant_id) -> dict:
    """Return grouped capabilities plus any tenant-specific extras."""
    curated = curated_capabilities()
    known = set(curated)
    extras: list[str] = []
    if tenant_id:
        for capabilities in Role.all_objects.filter(tenant_id=tenant_id).values_list(
            "capabilities", flat=True
        ):
            for capability in capabilities or []:
                code = str(capability).strip()
                if not code or code in known:
                    continue
                known.add(code)
                extras.append(code)
    extras.sort()

    groups = [
        {"label": label, "capabilities": list(capabilities)}
        for label, capabilities in CAPABILITY_GROUPS
    ]
    if extras:
        groups.append({"label": "Tenant-specific", "capabilities": extras})

    return {
        "capabilities": curated + extras,
        "groups": groups,
    }
