# Operator acceptance for rc40

This checklist describes software paths and outstanding human acceptance. It is
not a claim that real devices, stock or provider connections have been certified.

## Commercial B2B price lists

1. Deliberately assign `pricing.manage` to the price editor,
   `pricing.commercial.approve` to a different reviewer, and
   `pricing.commercial.publish` to the authorised publisher. The publisher may
   also be the editor; the approver must not have edited/submitted the list.
   New capabilities are not silently granted to existing tenant roles.
2. In HQ → Pricing → Commercial B2B price lists, create an unapproved draft.
   Enter a unique code, name, confirmed start date and a specific reason. New
   UI lists use KES; clones retain their source currency. No conversion is inferred.
3. Add confirmed SKU/unit prices and effective dates. A quantity break has its
   own positive minimum quantity and may share a start date with another break.
   Do not infer tablet/strip/box/bottle units from an imported price.
4. Submit the actual draft. The independent reviewer checks the displayed entries
   and approves or rejects with a reason. Any subsequent edit invalidates the
   decision; stale screens cannot publish. Refresh after uncertain requests;
   exact retries retain their command key rather than creating duplicate writes.
5. Publish only the currently approved contents. An overlapping active default
   list must be deliberately archived or have non-overlapping dates. Archiving
   blocks customers assigned to that list until their configuration is corrected;
   it must not silently fall back to an unrelated default. Plan that operational
   transition explicitly. Published prices are immutable: clone the next draft.

These are B2B lists, not retail price books. Customer-specific agreement,
promotion authoring/approval and commercial-profile assignment still need their
own governed operator workflows; list governance does not complete those paths.

## Reports

The new packs show customer order cohorts, customer creation cohorts, patient
medication-history entries, observed operator activity, open-till expected cash,
and FHIR idempotency observations. Read each data-basis description before use.

- Patient-history access requires both patient-read and clinical authority.
  Branch-restricted users remain restricted; an explicitly empty branch scope
  returns no branch records. Patient identity/narrative fields not required for
  the source contract are excluded. Recorded medication-history entries are not
  a net quantity or purchase-revenue total.
- Till cash projection is expected drawer cash, not physically counted cash,
  bank balances or a frozen Z report. It refuses historical-window filters.
- Order totals are not revenue/receivables. Activity counts are not performance
  rankings. FHIR observations are not exchange acceptance or certification.
- Downloads have audited receipts and validation links. Reports exceeding the
  source row limit refuse rather than silently truncating. 38 packs remain
  unavailable pending their ledgers/source definitions and acceptance contracts.

## Maintenance, native tills and real stock

- `/admin/` is an inspection-only maintenance surface, not a second business or
  password-write workflow. Use the governed HQ/API screens for changes.
- Windows POS remains signed managed-device version 1.0.5. Managers must complete
  approved certificate enrolment, installation, device activation and normal
  operator login. No new installer/version is implied by this server/HQ release.
- Managers still confirm real selling/pack units, batches and expiry dates for
  imported stock, then complete catalogue/price/quality controls before sale.
  Quarantine or blocked items must not be released from guesses or demo evidence.
- Managers test the actual scanner, Windows USB receipt/label printers and drawer
  connected through the printer. Confirm exact printer/model protocol first;
  no guessed cash-drawer pulse is enabled as evidence of compatibility.
- Android production signing remains pending its approved key. External
  DHA/HWR/PPB/SHA/insurer/M-PESA connections remain disabled templates until
  approved endpoints, secret-manager configuration and acceptance are supplied.
- VPS free capacity remains a separate operational concern. This release does
  not authorise deletion of unrelated projects, production facts or rollback
  material to claim readiness.
