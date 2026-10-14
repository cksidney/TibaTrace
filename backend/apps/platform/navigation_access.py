"""HQ navigation presentation from current server-side identity/capabilities.

This is not API authority: endpoint/service permission checks remain mandatory.
Platform identity is explicit; a tenant role containing '*' is not an owner.
"""

OWNER_VIEWS = ("executive", "network", "integration", "platform_owner")
TENANT_VIEWS = {
    "people": ("patients.read", "practitioners.read", "customers.read", "sales.read", "sales.manage"),
    "catalogue": ("catalogue.read", "catalogue.manage", "catalogue.activate"),
    "inventory": ("inventory.read", "inventory.manage"),
    "operations": ("procurement.read", "procurement.write", "procurement.approve", "quality.release"),
    "commerce": ("sales.read", "sales.manage"),
    "pricing": ("pricing.read", "pricing.manage", "pricing.commercial.approve", "pricing.commercial.publish",
                "pricing.price_book.manage", "pricing.price_book.approve", "pricing.price_book.publish"),
    "cash": ("pos.shift.manage", "pos.session.view", "pos.report.read", "pos.cash.read",
             "dispensing.complete", "prescriptions.record_payment", "pos.retail.checkout"),
    "insurance": ("insurance.read", "insurance.manage"),
    "clinical": ("clinical.read", "prescriptions.read", "dispensing.read", "cds.read", "terminology.read"),
    "regulatory": ("practitioners.read", "prescribers.verify", "recalls.read", "recalls.manage"),
    "reports": ("reports.view",),
    "governance": ("audit.read", "documents.read"),
    "access": ("identity.manage",),
}


def hq_navigation_access(user, tenant_id):
    owner = bool(user.is_active and (user.is_platform_admin or user.is_superuser))
    capabilities = user.effective_capabilities(tenant_id=tenant_id)

    def has_any(required):
        return "*" in capabilities or bool(set(required) & capabilities)

    allowed = ["overview"] if user.is_active else []
    if owner:
        allowed += list(OWNER_VIEWS) + list(TENANT_VIEWS) + ["gs1"]
    elif user.is_active and tenant_id and str(user.tenant_id) == str(tenant_id):
        allowed += [view for view, required in TENANT_VIEWS.items() if has_any(required)]
        if has_any(("catalogue.read", "catalogue.manage")) and has_any(("inventory.read", "inventory.manage")):
            allowed.append("gs1")
    return {
        "is_platform_owner": owner,
        "allowed_views": allowed,
        "show_pos_handoff": owner or (bool(tenant_id) and ("*" in capabilities or any(cap.startswith("pos.") for cap in capabilities))),
    }


def scoped_dashboard_links(rows, allowed_views):
    """Keep tenant observations but do not advertise forbidden destinations."""
    return [
        {key: value for key, value in row.items()
         if key != "href" or value.removeprefix("#").split("/")[0] in allowed_views}
        for row in rows
    ]
