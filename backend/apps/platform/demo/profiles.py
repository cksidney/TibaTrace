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

# ---------------------------------------------------------------------------
# Stage 2A master data
# ---------------------------------------------------------------------------

#: Dated content version. Bumping it changes the manifest digest, which
#: invalidates a prior approval -- deliberately, because the approval authorised
#: one exact plan.
DEMO_VERSION = "2026.08.03"

#: Human-facing scenario identity.
SCENARIO_LABEL = "Nairobi Chemists Enterprise Pilot"
MASTER_DATA_SCENARIO_VERSION = "1.0"

#: Deterministic seed for the pilot. The engine takes the seed as an argument;
#: this is the authorised value, recorded so the manifest and the command agree.
PILOT_RANDOM_SEED = 83492011


@dataclass(frozen=True)
class MasterDataTargets:
    """Bounded counts for Stage 2A.

    Counts live here rather than in generator code so that the plan is
    reviewable in one place and the manifest can be produced without running
    anything. A generator that computed its own counts inline would make the
    dry run a different code path from the real run, which is exactly the
    situation where a dry run stops predicting the thing it approves.
    """

    retail_branches: int = 2
    warehouses: int = 1
    head_offices: int = 1
    departments: int = 13
    users: int = 16
    practitioners: int = 12
    patients: int = 500
    manufacturers: int = 14
    suppliers: int = 18
    skus: int = 400
    insurers: int = 6
    insurance_plans: int = 12
    price_books: int = 6

    def as_counts(self) -> dict[str, int]:
        return {
            "head_offices": self.head_offices,
            "retail_branches": self.retail_branches,
            "warehouses": self.warehouses,
            "departments": self.departments,
            "users": self.users,
            "practitioners": self.practitioners,
            "patients": self.patients,
            "manufacturers": self.manufacturers,
            "suppliers": self.suppliers,
            "skus": self.skus,
            "insurers": self.insurers,
            "insurance_plans": self.insurance_plans,
            "price_books": self.price_books,
        }


#: Full-scale pilot targets, matching the authorised brief.
MASTER_DATA_PILOT = MasterDataTargets()

#: Reduced scale for local/disposable execution. Same code path, same stages,
#: smaller counts -- so a local run exercises every stage without seeding 500
#: patients on a laptop.
MASTER_DATA_LOCAL = MasterDataTargets(
    departments=13, users=16, practitioners=12, patients=25,
    manufacturers=8, suppliers=10, skus=40, insurers=6,
    insurance_plans=8, price_books=2,
)

MASTER_DATA_TARGETS: dict[str, MasterDataTargets] = {
    "small": MASTER_DATA_LOCAL,
    "medium": MasterDataTargets(patients=150, skus=150, price_books=2),
    "large": MASTER_DATA_PILOT,
}


def get_master_data_targets(scale: str) -> MasterDataTargets:
    try:
        return MASTER_DATA_TARGETS[scale]
    except KeyError:
        known = ", ".join(sorted(MASTER_DATA_TARGETS))
        raise KeyError(f"Unknown scale {scale!r}. Available: {known}") from None


#: Domains Stage 2A must not touch. Named explicitly so the validator asserts
#: against a list rather than a memory of what "transactional" meant.
STAGE_2A_FORBIDDEN_DOMAINS = {
    "purchase_requisitions": "procurement is Stage 2B",
    "purchase_orders": "procurement is Stage 2B",
    "goods_receipts": "procurement is Stage 2B",
    "inventory_batches": "batches arrive through procurement in Stage 2B",
    "inventory_ledger_entries": "the ledger is transactional history",
    "inventory_balances": "derived from the ledger",
    "inventory_reservations": "transactional",
    "stock_transfers": "transactional",
    "stocktakes": "transactional",
    "prescriptions": "clinical history is Stage 2C",
    "dispensing_episodes": "clinical history is Stage 2C",
    "pos_sales": "transactional",
    "payments": "transactional",
    "claims": "transactional",
    "remittances": "transactional",
    "recalls": "transactional",
    "finance_postings": "no finance domain exists, and postings are transactional",
}


PROFILES: dict[str, DemoProfile] = {PILOT.key: PILOT}


def get_profile(key: str) -> DemoProfile:
    try:
        return PROFILES[key]
    except KeyError:
        known = ", ".join(sorted(PROFILES)) or "none"
        raise KeyError(f"Unknown demo profile {key!r}. Available: {known}") from None
