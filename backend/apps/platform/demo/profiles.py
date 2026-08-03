"""Demo scenario profiles.

A profile declares intent -- how many of what, over what period -- and nothing
about how it is produced. Stage 1 ships the pilot profile only; its purpose is
correctness and runtime measurement, not volume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Bumping this invalidates prior manifests and approvals, which is the point:
#: an approval authorises one exact plan produced by one exact version.
SCENARIO_VERSION = "1.0.0"

SCENARIO_NAME = "nairobi-chemists"


@dataclass(frozen=True)
class DemoProfile:
    key: str
    label: str
    months_of_history: int
    counts: dict[str, int]
    #: Domains this profile deliberately does not populate, with the reason.
    excluded_domains: dict[str, str] = field(default_factory=dict)

    def planned_total(self) -> int:
        return sum(self.counts.values())


#: Finance exclusions are not a scoping preference -- these domains have no
#: models or services in this repository, so there is nothing authoritative to
#: post through. See docs/demo/NAIROBI_CHEMISTS_DEMO_DATA_ARCHITECTURE.md.
_FINANCE_EXCLUSIONS = {
    "general_ledger": "no GL app, model or service exists",
    "trial_balance": "derived from a general ledger that does not exist",
    "profit_and_loss": "derived from a general ledger that does not exist",
    "balance_sheet": "derived from a general ledger that does not exist",
    "vat_return": "no VAT domain exists",
    "ar_ageing": "no accounts-receivable domain exists",
    "ap_ageing": "no accounts-payable domain exists",
    "supplier_invoices": "no SupplierInvoice model exists",
    "close_packs": "no period-close domain exists",
}

PILOT = DemoProfile(
    key="nairobi-chemists-pilot",
    label="Nairobi Chemists pilot (correctness and runtime measurement)",
    months_of_history=9,
    counts={
        "branches": 2,
        "warehouses": 1,
        "users": 16,
        "patients": 500,
        "stocked_skus": 400,
        "batches": 750,
        "inventory_ledger_entries": 4000,
        "sales_dispensing_events": 1500,
        "prescriptions": 375,
        "claims": 75,
        "suppliers": 8,
        "purchase_orders": 40,
        "stock_transfers": 20,
        "recalls": 2,
        "shifts": 60,
        "notifications": 120,
    },
    excluded_domains=_FINANCE_EXCLUSIONS,
)

PROFILES: dict[str, DemoProfile] = {PILOT.key: PILOT}


def get_profile(key: str) -> DemoProfile:
    try:
        return PROFILES[key]
    except KeyError:
        known = ", ".join(sorted(PROFILES)) or "none"
        raise KeyError(f"Unknown demo profile {key!r}. Available: {known}") from None
