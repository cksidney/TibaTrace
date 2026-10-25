"""Curated capability catalogue for role governance UI.

Capabilities remain free-form strings on Role.capabilities; this catalogue is a
presentation and discovery aid so operators can grant known authorities without
typing opaque strings. Anything already assigned on a tenant role is always
included even if it is not in the curated list.
"""
from __future__ import annotations

from apps.identity.models import Role

CAPABILITY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("DHA integrations", ("dha.configure", "dha.identity", "dha.terminology", "dha.exchange", "dha.claims", "dha.emergency")),
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
            "inventory.transfer.request",
            "inventory.transfer.approve",
            "inventory.transfer.dispatch",
            "inventory.transfer.receive",
        ),
    ),
    (
        "Medicine catalogue",
        (
            "catalogue.read",
            "catalogue.manage",
            "catalogue.activate",
        ),
    ),
    (
        "People & practitioner governance",
        (
            "patients.read",
            "patients.create",
            "patients.write",
            "patients.sensitive.view",
            "patients.identity.view",
            "patients.identity.manage",
            "patients.allergy.record",
            "patients.clinical_summary.manage",
            "practitioners.read",
            "practitioners.write",
            "prescribers.verify",
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
            "pricing.commercial.approve",
            "pricing.commercial.publish",
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
            "prescriptions.record_payment",
            "prescriptions.payment_exempt",
            "prescriptions.intervention.create",
            "prescriptions.substitution.approve",
            "cds.read",
            "clinical.read",
            "dispensing.read",
            "dispensing.reserve",
            "dispensing.allocate",
            "dispensing.prepare",
            "dispensing.check",
            "dispensing.counsel",
            "dispensing.supply",
            "dispensing.reverse",
            "dispensing.return.receive",
            "dispensing.complete",
        ),
    ),
    (
        "Point of sale",
        (
            "pos.payment.collect",
            "pos.transaction.create",
            "pos.transaction.read",
            "pos.transaction.manage",
            "pos.payment.cash.accept",
            "pos.refund.request",
            "pos.refund.approve",
            "pos.refund.cash.execute",
            "pos.shift.manage",
            "pos.session.view",
            "pos.report.read",
            "pos.cash.read",
            "pos.device.read",
            "pos.device.manage",
            "pos.label.print",
            "pos.document.read",
            "pos.document.print",
            "pos.document.reprint",
            "pos.document.cancel",
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
