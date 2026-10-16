# POS checkout and recovery — rc50 / Windows 1.0.9

The Windows till uses the same server payment ledger for clinical and retail
checkout. Record an amount in full, or record a part and settle the remaining
balance with another method. Cash received and change are separate from the
amount applied to the sale. Card collection and card refunds use an external
terminal: record its terminal ID and transaction approval reference together.
TibaTrace does not control the terminal or collect card numbers/PINs.

Clinical readiness, recorded pricing, tenant/branch permissions, the assigned
open register, business day and operator shift are checked on the server.
A partial or pending payment cannot release medicine. Retail stock is reserved
before the first collection and issued only when the full balance settles.
Basket quantities and prices freeze once collection begins. Completed retail
receipts and ledger parts contribute once to reports; only actual cash affects
the drawer. Unresolved payments block Z closure.

## Interrupted collection

The native encrypted journal saves the command before sending. A definite
refusal retains the input for correction. A timeout blocks further collection:
use **Check original payment**, then retry only the saved command if absent.
Keep the original key. Restarting the till recovers unfinished commands.
Offline cash commands can be staged, but remain unconfirmed: no receipt,
stock issue or supply is claimed until the server accepts the original command.
A fully recorded payment whose stock handover fails offers **Finish paid sale**;
it does not collect money again.

## Returns

An unfinished retail checkout can request a payment void. A different authorised
supervisor must confirm original-method returns on its original open register.
Card portions require distinct terminal refund references. Only then does the
system void the sale, release reservations, and queue its return receipt.

Completed sales use **Returns and refunds**, with the original receipt, reason,
line quantities and independent approval. The server reserves both return
quantity and original-payment budgets while requests await review. Cash and
card portions are frozen for approval and recorded separately. Physical goods
enter an authorised quarantine location against their actual original batch;
they do not become saleable. Replayed refund keys cannot change the references.

## External integrations

M-PESA requires supplied Daraja API credentials and validation. STK acceptance
is pending; only a server-authenticated Daraja query settles a known attempt.
The callback acknowledges delivery without trusting its contents as settlement.
Timeouts/5xx remain unknown and cannot be blindly reinitiated. If a request
never yields a CheckoutRequestID, reconcile with the provider before releasing
its payment allocation. Mobile reversals remain unavailable until a verified
Daraja reversal integration is supplied; cash cannot substitute for them.

VSCU has a separate durable invoice/credit-note outbox. Registered VSCU device,
taxpayer/branch registration, invoice baseline, item codes, classification,
units and tax mappings must be supplied and validated. Credit notes reference
the accepted original invoice. Only an accepted VSCU response with receipt
number, signature, internal data and SDC ID becomes fiscal evidence and queues
a fiscal document. Internal receipts remain explicitly internal. UNKNOWN or
SENDING outcomes require reconciliation; never automatically resend an invoice.
Physical print acceptance and KRA device/integration certification are separate
from local software tests. This release does not establish live certification.

Insurance/account receivables and zero-payable approvals are not tender options
in this checkout. They must use their governed business workflows; entering a
reference or zero amount cannot mark a prescription paid.

## Server configuration

Set `TIBATRACE_CHECKOUT_CONNECTIONS` to JSON keyed by `tenantUUID/branchUUID`.
Never place secret values in that JSON or in the app bundle. Example shape:

```json
{
  "TENANT_UUID/BRANCH_UUID": {
    "MPESA": {
      "enabled": false,
      "validated": false,
      "environment": "sandbox",
      "short_code": "PROVIDER_SHORT_CODE",
      "callback_url": "https://tibatrace.esenai.co.ke/api/pos/payments/mpesa/callback/",
      "consumer_key_env": "TIBATRACE_DARAJA_CONSUMER_KEY",
      "consumer_secret_env": "TIBATRACE_DARAJA_CONSUMER_SECRET",
      "passkey_env": "TIBATRACE_DARAJA_PASSKEY"
    },
    "VSCU": {
      "enabled": false,
      "validated": false,
      "base_url": "http://127.0.0.1:8080",
      "tin": "REGISTERED_KRA_PIN",
      "bhf_id": "00",
      "last_invoice_number": 0,
      "tax_rates": {"A": 0},
      "items": {
        "SKU_UUID": {
          "item_code": "REGISTERED_ITEM_CODE",
          "classification_code": "REGISTERED_CLASSIFICATION",
          "package_unit": "REGISTERED_CODE",
          "quantity_unit": "REGISTERED_CODE",
          "tax_type": "A"
        }
      }
    }
  }
}
```

Remote VSCU endpoints require HTTPS. In Docker, loopback is the container;
provide a reachable authenticated server-side endpoint for the registered device.
Do not set `validated` until sandbox/device evidence, provider reconciliation,
fiscal item/tax mappings, fiscal receipt formatting and printer checks pass.
Celery beat schedules provider reconciliation and fiscal processing every minute.

Implementation follows the [KRA VSCU v2 specification](https://www.kra.go.ke/images/publications/VSCU_Specification_Document_v2.0.pdf),
including `/trnsSales/saveSales` and original-invoice-linked credit notes.
