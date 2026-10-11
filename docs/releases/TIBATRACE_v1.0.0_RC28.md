# TibaTrace v1.0.0-rc28 — cash-only retail checkout

Adds a complete cash-only retail settlement path for a register-bound sale:
cash tender and change are recorded once, eligible stock is issued through the
FEFO inventory ledger, an immutable internal receipt is created, and the sale
is included in till cash reconciliation. A durable receipt print job is queued
best-effort so a print-queue failure cannot undo a completed sale. Windows and
Android POS screens now collect cash, show exact change, display the receipt,
and allow the cashier to start the next sale.

Card and M-PESA retail settlement remain disabled. The receipt is explicitly an
internal sales receipt, not a fiscal/eTIMS receipt. Print jobs use the existing
simulator until a Manager completes physical printer acceptance; no scanner,
printer, cash-drawer or fiscal integration is certified by this release.

This release does not solve the tenant catalogue/price publication gap, supply
missing batches/expiry data, add retail refunds, enable offline retail checkout,
or provision live regulator/payment-provider connections.
