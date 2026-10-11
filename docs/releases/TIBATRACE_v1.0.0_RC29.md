# TibaTrace v1.0.0-rc29 — cash-only retail release evidence correction

Carries the cash-only retail API/HQ release from rc28. The rc28 server image
release correctly failed closed because its declared migration checklist
omitted `pos_transactions.0002_retailcashreceipt`. This release corrects that
checklist and adds a regression test proving the migration creates one receipt
table and seven constraints, with no destructive or data operations.

Cash tender and change are recorded once, eligible stock is issued through the
FEFO inventory ledger, an immutable internal receipt is created, and sales are
included in till cash reconciliation. Receipt printing is best-effort through
the durable print queue. The signed Windows POS 1.0.4 managed-install kit remains
the matching client release; this server candidate does not rebuild or retag it.
Android release publication still requires the Managers' release-signing setup.

Card and M-PESA retail settlement remain disabled. Receipts are internal,
non-fiscal sales receipts, not eTIMS receipts. Physical scanner, printer and
cash-drawer acceptance remains with Managers.

This release does not solve the tenant catalogue/price publication gap, supply
missing real pack units/batches/expiry data, add retail refunds, enable offline
retail checkout, or provision live regulator/payment-provider connections.
