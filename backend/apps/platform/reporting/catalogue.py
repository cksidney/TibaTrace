"""Enterprise report catalogue for downloadable HQ packs."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReportSpec:
    id: str
    category: str
    category_label: str
    name: str
    description: str
    audience: str
    cadence: str


CATEGORIES: tuple[tuple[str, str], ...] = (
    ("executive", "Executive Reports"),
    ("sales", "Sales & Dispensing Reports"),
    ("procurement", "Procurement Reports"),
    ("inventory", "Inventory Reports"),
    ("finance", "Finance Reports"),
    ("quality", "Quality Reports"),
    ("clinical", "Clinical Reports"),
    ("controlled", "Controlled Drug Reports"),
    ("regulatory", "Regulatory Reports"),
    ("logistics", "Logistics Reports"),
    ("crm", "CRM Reports"),
    ("hr", "HR & Operations Reports"),
    ("audit", "Audit Reports"),
    ("analytics", "Analytics & Forecasting"),
    ("security", "Security Reports"),
)


def _specs() -> list[ReportSpec]:
    rows: list[tuple[str, str, str, str, str, str]] = [
        # Executive
        ("executive", "exec-dashboard", "Executive Dashboard", "Consolidated leadership KPIs across the active workspace.", "Leadership", "Real-time"),
        ("executive", "exec-revenue", "Revenue Summary", "Sales and dispensing revenue by branch, channel and period.", "Finance / Leadership", "Daily"),
        ("executive", "exec-inventory-value", "Inventory Value", "On-hand stock valuation across locations and quality states.", "Finance / Operations", "Daily"),
        ("executive", "exec-cash-position", "Cash Position", "Open tills, expected drawers and unexplained variances.", "Finance", "Intraday"),
        ("executive", "exec-receivables", "Outstanding Receivables", "Customer and insurer balances awaiting settlement.", "Finance", "Daily"),
        ("executive", "exec-payables", "Outstanding Payables", "Supplier liabilities from matched receipts and invoices.", "Finance / Procurement", "Daily"),
        ("executive", "exec-regulatory-alerts", "Regulatory Alerts", "Open compliance exceptions requiring management attention.", "Compliance", "Daily"),
        ("executive", "exec-quality-kpis", "Quality KPIs", "Holds, releases, deviations and excursion indicators.", "Quality / Leadership", "Weekly"),
        # Sales
        ("sales", "sales-period", "Daily/Weekly/Monthly Sales", "Period sales totals with branch and tender breakdown.", "Commercial", "Daily"),
        ("sales", "sales-by-branch", "Sales by Branch", "Comparative sales performance across network locations.", "Commercial", "Daily"),
        ("sales", "sales-by-pharmacist", "Sales by Pharmacist", "Dispensing and verification throughput by practitioner.", "Clinical ops", "Daily"),
        ("sales", "sales-by-customer", "Sales by Customer", "Commercial customer order and fulfilment history.", "Commercial", "On demand"),
        ("sales", "sales-by-insurer", "Sales by Insurer", "Insured dispensing volumes and claim values by payer.", "Insurance ops", "Daily"),
        ("sales", "sales-rx-dispensing", "Prescription Dispensing", "Prescription workflow from intake through supply.", "Clinical ops", "Real-time"),
        ("sales", "sales-clinical-holds", "Clinical Holds", "Prescriptions paused for clinical or legal review.", "Clinical ops", "Real-time"),
        ("sales", "sales-clinical-overrides", "Clinical Overrides", "CDS and clinical screening overrides with rationale.", "Clinical governance", "Daily"),
        ("sales", "sales-waiting-time", "Patient Waiting Time", "Queue and turnaround from receipt to collection.", "Operations", "Hourly"),
        # Procurement
        ("procurement", "proc-requisitions", "Purchase Requisitions", "Raised, approved and fulfilled stock requests.", "Procurement", "Daily"),
        ("procurement", "proc-orders", "Purchase Orders", "Open and closed POs with expected delivery and value.", "Procurement", "Daily"),
        ("procurement", "proc-grn", "Goods Receipts", "GRNs, discrepancies and receipt completeness.", "Procurement / Warehouse", "Daily"),
        ("procurement", "proc-supplier-performance", "Supplier Performance", "OTIF, quality holds and return rates by supplier.", "Procurement", "Weekly"),
        ("procurement", "proc-lead-time", "Lead Time", "Order-to-receipt lead times by supplier and SKU.", "Procurement", "Weekly"),
        ("procurement", "proc-price-variance", "Price Variance", "PO versus invoice and catalogue price differences.", "Finance / Procurement", "Weekly"),
        ("procurement", "proc-returns", "Supplier Returns", "Returned batches and credit status.", "Procurement / Quality", "Weekly"),
        # Inventory
        ("inventory", "inv-balance", "Stock Balance", "On-hand, reserved and available quantities by location.", "Warehouse", "Real-time"),
        ("inventory", "inv-batch", "Batch Inventory", "Lot-level balances with expiry and quality state.", "Warehouse / Quality", "Daily"),
        ("inventory", "inv-valuation", "Inventory Valuation", "Financial valuation of stock by location and state.", "Finance", "Daily"),
        ("inventory", "inv-fefo", "FEFO Analysis", "First-expiry-first-out compliance and reservation coverage.", "Warehouse", "Daily"),
        ("inventory", "inv-expiry", "Expiry Report", "Batches approaching or past expiry thresholds.", "Quality / Warehouse", "Daily"),
        ("inventory", "inv-velocity", "Slow/Fast Moving Items", "Movement velocity bands for replenishment planning.", "Procurement", "Weekly"),
        ("inventory", "inv-dead-stock", "Dead Stock", "Items with no movement within the dormancy window.", "Commercial / Finance", "Monthly"),
        ("inventory", "inv-movements", "Stock Movements", "Append-only ledger of receipts, issues, transfers and adjustments.", "Warehouse / Audit", "On demand"),
        ("inventory", "inv-cycle-count", "Cycle Count Variances", "Count differences requiring investigation or write-off.", "Warehouse / Finance", "Weekly"),
        # Finance
        ("finance", "fin-gl", "General Ledger", "Posted financial movements for the reporting period.", "Finance", "Monthly"),
        ("finance", "fin-trial-balance", "Trial Balance", "Debit and credit balances by account.", "Finance", "Monthly"),
        ("finance", "fin-cash-book", "Cash Book", "Till and bank cash movements with shift linkage.", "Finance", "Daily"),
        ("finance", "fin-vat", "VAT Report", "Output and input tax summary for filing periods.", "Finance", "Monthly"),
        ("finance", "fin-ar", "Accounts Receivable", "Ageing of customer and insurer receivables.", "Finance", "Daily"),
        ("finance", "fin-ap", "Accounts Payable", "Ageing of supplier payables from matched invoices.", "Finance", "Daily"),
        ("finance", "fin-profitability", "Profitability", "Margin analysis by branch, SKU class and payer mix.", "Leadership / Finance", "Monthly"),
        # Quality
        ("quality", "qa-capa", "CAPA", "Corrective and preventive actions with ageing and owners.", "Quality", "Weekly"),
        ("quality", "qa-deviations", "Deviations", "Recorded process and product deviations.", "Quality", "Weekly"),
        ("quality", "qa-recalls", "Recalls", "Active and historical recall actions with batch impact.", "Quality / Regulatory", "On demand"),
        ("quality", "qa-temperature", "Temperature Excursions", "Cold-chain and storage excursions tied to received batches.", "Quality", "Daily"),
        ("quality", "qa-quarantine", "Quarantine Stock", "Batches held pending inspection or investigation.", "Quality / Warehouse", "Daily"),
        ("quality", "qa-released", "Released Stock", "Quality-released batches available for sale or dispensing.", "Quality", "Daily"),
        ("quality", "qa-supplier", "Supplier Quality", "Qualification status and quality performance by supplier.", "Quality / Procurement", "Monthly"),
        # Clinical
        ("clinical", "clin-interactions", "Drug Interactions", "Screening findings for interacting therapies.", "Clinical governance", "Daily"),
        ("clinical", "clin-screening", "Clinical Screening Outcomes", "CDS outcomes against published knowledge releases.", "Clinical governance", "Daily"),
        ("clinical", "clin-overrides", "Override Reports", "Pharmacist overrides with reason codes and audit linkage.", "Clinical governance", "Daily"),
        ("clinical", "clin-allergy", "Allergy Alerts", "Allergy-related screening alerts and acknowledgements.", "Clinical ops", "Daily"),
        ("clinical", "clin-interventions", "Pharmacist Interventions", "Documented clinical interventions during dispensing.", "Clinical governance", "Weekly"),
        # Controlled
        ("controlled", "cd-register", "Controlled Drug Register", "Running register of controlled substance balances.", "Pharmacist in charge", "Daily"),
        ("controlled", "cd-receipts", "Receipts", "Inbound controlled stock with witness and documentation.", "Pharmacist in charge", "On demand"),
        ("controlled", "cd-issues", "Issues", "Dispensed and issued controlled quantities.", "Pharmacist in charge", "Daily"),
        ("controlled", "cd-destruction", "Destruction", "Destruction events with authorisation trail.", "Compliance", "On demand"),
        ("controlled", "cd-audit", "Audit Trail", "Immutable trail of controlled stock actions.", "Audit / Compliance", "On demand"),
        # Regulatory
        ("regulatory", "reg-ppb", "PPB Reports", "Exports aligned to Pharmacy and Poisons Board reporting needs.", "Regulatory", "Periodic"),
        ("regulatory", "reg-traceability", "Batch Traceability", "Forward and backward batch genealogy across supply and dispensing.", "Quality / Regulatory", "On demand"),
        ("regulatory", "reg-gdp-gsp", "GDP/GSP Compliance", "Good distribution and storage practice indicators.", "Compliance", "Monthly"),
        ("regulatory", "reg-pv", "Pharmacovigilance", "Adverse event and safety signal reporting package.", "Clinical / Regulatory", "On demand"),
        # Logistics
        ("logistics", "log-shipments", "Shipment Tracking", "Outbound shipment status across the fulfilment network.", "Logistics", "Real-time"),
        ("logistics", "log-delivery", "Delivery Performance", "On-time delivery and failed-attempt rates.", "Logistics", "Weekly"),
        ("logistics", "log-pod", "POD Status", "Proof-of-delivery capture and exceptions.", "Logistics", "Daily"),
        ("logistics", "log-routes", "Route Performance", "Route utilisation and stop-level outcomes.", "Logistics", "Weekly"),
        # CRM
        ("crm", "crm-growth", "Customer Growth", "New, active and dormant commercial customer trends.", "Commercial", "Monthly"),
        ("crm", "crm-patient-history", "Patient Purchase History", "Patient-linked dispensing history for continuity of care.", "Clinical ops", "On demand"),
        ("crm", "crm-insurance-util", "Insurance Utilization", "Member utilisation and benefit consumption by insurer.", "Insurance ops", "Monthly"),
        # HR
        ("hr", "hr-productivity", "Staff Productivity", "Operator throughput across dispensing and till activities.", "Operations", "Weekly"),
        ("hr", "hr-register-sessions", "Register Sessions", "Open and closed till sessions by operator and register.", "Finance / Operations", "Intraday"),
        ("hr", "hr-x-reports", "X Reports", "Interim till readings without closing the session.", "Finance", "On demand"),
        ("hr", "hr-z-reports", "Z Reports", "End-of-day till closures with declared cash and variance.", "Finance", "Daily"),
        ("hr", "hr-cash-variance", "Cash Variance", "Unexplained drawer differences requiring explanation.", "Finance / Audit", "Daily"),
        ("hr", "hr-offline", "Offline Transactions", "Transactions captured while offline awaiting sync.", "Operations / IT", "Intraday"),
        ("hr", "hr-sync-failures", "Sync Failures", "Failed device and branch synchronisation attempts.", "IT", "Intraday"),
        # Audit
        ("audit", "audit-user", "User Audit Trail", "Immutable user activity across governed HQ and POS actions.", "Audit / Security", "On demand"),
        ("audit", "audit-financial", "Financial Audit", "Cash, pricing and settlement actions with actor attribution.", "Audit / Finance", "On demand"),
        ("audit", "audit-inventory", "Inventory Audit", "Stock ledger and adjustment audit package.", "Audit / Warehouse", "On demand"),
        ("audit", "audit-clinical", "Clinical Audit", "Screening, override and dispensing clinical decisions.", "Clinical governance", "On demand"),
        ("audit", "audit-config", "Configuration Changes", "Changes to roles, pricing, catalogue selection and tenant settings.", "Audit / Security", "On demand"),
        # Analytics
        ("analytics", "an-abc-xyz", "ABC/XYZ Analysis", "Value and demand-variability classification of the catalogue.", "Procurement / Commercial", "Monthly"),
        ("analytics", "an-demand-forecast", "Demand Forecast", "Forward demand estimate by SKU and branch.", "Procurement", "Weekly"),
        ("analytics", "an-inventory-forecast", "Inventory Forecast", "Projected stock cover and replenishment need.", "Operations", "Weekly"),
        ("analytics", "an-revenue-forecast", "Revenue Forecast", "Projected revenue by branch and channel.", "Leadership", "Monthly"),
        ("analytics", "an-basket", "Basket Analysis", "Co-purchase patterns across dispensing and OTC sales.", "Commercial", "Monthly"),
        # Security
        ("security", "sec-access-grants", "User Access & Role Grants", "Active accounts, role assignments and account status changes.", "Security / Identity", "On demand"),
        ("security", "sec-capability-matrix", "Capability Coverage Matrix", "Role × capability grants for tenant authority review.", "Security / Identity", "On demand"),
        ("security", "sec-permission-changes", "Permission Change Report", "Recent role capability and user-role grant mutations.", "Security", "Daily"),
        ("security", "sec-service-accounts", "Service Account Credentials", "Machine identities, fingerprints and granted capabilities.", "Security / IT", "Weekly"),
        ("security", "sec-session-assurance", "Session & Authentication Assurance", "Authenticated sessions, password resets and suspended accounts.", "Security", "Daily"),
        ("security", "sec-audit-trail", "Security Audit Trail", "Security-relevant audit events and failed domain events.", "Security / Audit", "On demand"),
        ("security", "sec-tenant-isolation", "Tenant Isolation Posture", "Cross-tenant boundary checks and isolation exceptions.", "Security / Platform", "Release"),
        ("security", "sec-fhir-idempotency", "FHIR Exchange Integrity", "Idempotent FHIR writes, duplicate protection and actor attribution.", "Security / Interop", "Daily"),
        ("security", "sec-forced-closures", "Forced Register Closures", "Till closures performed outside the accountable operator path.", "Security / Finance", "Daily"),
        ("security", "sec-cash-exceptions", "Cash Exception Reviews", "Variance investigations opened, under review and resolved.", "Security / Finance", "Daily"),
        ("security", "sec-clinical-authz", "Clinical Authorisation Denials", "Capability-denied clinical actions and override authentication events.", "Security / Clinical", "Daily"),
        ("security", "sec-document-access", "Document Access & Integrity", "Document downloads, hash verification and token-bound access.", "Security", "Weekly"),
        ("security", "sec-dependency-posture", "Dependency & Vulnerability Posture", "Advisory scan status for dependencies and container images.", "Security / Engineering", "Release"),
        ("security", "sec-secret-scan", "Secret Scan Findings", "Source-tree secret scan baseline and outstanding findings.", "Security", "Release"),
    ]
    category_labels = dict(CATEGORIES)
    return [
        ReportSpec(
            id=report_id,
            category=category,
            category_label=category_labels[category],
            name=name,
            description=description,
            audience=audience,
            cadence=cadence,
        )
        for category, report_id, name, description, audience, cadence in rows
    ]


REPORTS: dict[str, ReportSpec] = {spec.id: spec for spec in _specs()}


def list_reports() -> list[ReportSpec]:
    return list(REPORTS.values())


def get_report(report_id: str) -> ReportSpec | None:
    return REPORTS.get(report_id)
