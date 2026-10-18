# POS checkout and recovery — rc50 / Windows 1.0.9

The Windows till uses the same server payment ledger for clinical and retail
checkout. Record an amount in full, or record a part and settle the remaining
balance with another method. Cash received and change are separate from the
amount applied to the sale. Card collection uses the tenant's installed adapter
when enabled and validated; otherwise the operator records an external terminal
approval. Card numbers and PINs are entered only on the terminal. Card refunds
retain their original provider and require its approved refund procedure.

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

Set `TIBATRACE_CHECKOUT_CONNECTIONS` to JSON keyed by tenant UUID. A branch
entry under `tenantUUID/branchUUID` may override a tenant default for a distinct
terminal or acquirer account. Never place secret values in that JSON or in the
app bundle; store only server environment-variable names. Example shape:

```json
{
  "TENANT_UUID": {
    "CARD": {
      "enabled": false,
      "validated": false,
      "provider_code": "INSTALLED_CARD_ADAPTER",
      "label": "Card terminal",
      "terminal_id": "REGISTERED_TERMINAL_ID",
      "terminals": {"POS_DEVICE_ID": "REGISTERED_TERMINAL_ID"},
      "credentials_env": {
        "api_key": "TIBATRACE_TENANT_CARD_API_KEY"
      },
      "manual_fallback": false,
      "manual_refunds": false
    },
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
  },
  "TENANT_UUID/BRANCH_UUID": {
    "CARD": {
      "terminal_id": "BRANCH_TERMINAL_ID"
    },
    "MPESA": {
      "short_code": "BRANCH_PAYBILL_OR_TILL",
      "callback_url": "https://tibatrace.example.test/api/pos/payments/mpesa/callback/"
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

Card and Daraja settings are resolved from the sale's tenant and branch on the
server. `provider_code` selects a connector already installed in the server
registry; configuration cannot import or run code. A connector implements
initiate, status query and authenticated-event parsing against the normalized
payment contract. Provider credentials are resolved only from the named server
environment variables and are never returned by the till API. The ledger stores
the connector code, request reference, provider reference, status, event hash
and settlement source so reconciliation and refunds retain their provider
context. Manual card approval remains available when integration is disabled;
when integration is enabled it is blocked unless `manual_fallback` is explicitly
enabled for that tenant.

For multiple tills, `terminals` maps each approved POS device ID to its physical
terminal; an unmapped device cannot start a card request when this mapping is
present. A single-terminal branch may omit `terminals` and use `terminal_id`.
An installed connector registers its factory through
`payment_providers.register_adapter`; the factory receives tenant, branch,
non-secret config and resolved credentials and must implement the provider
contract. Every remote request uses the persisted attempt reference as its
stable provider idempotency/correlation key. A successful acknowledgement stays
pending until a trusted status query or authenticated callback confirms amount,
currency and provider reference.

Card callbacks use
`/api/pos/payments/providers/PROVIDER_CODE/callback/` and must echo the signed
top-level `request_reference`. That reference locates an existing attempt;
the tenant's adapter verifies the provider signature before a settlement is
recorded. `authenticate_event` receives `raw_body` with the exact request bytes
for signature schemes that cannot authenticate re-encoded JSON. Invalid
signatures cannot reserve an event ID or block a legitimate
redelivery. A callback arriving before the initial response cannot be overwritten
by that later acknowledgement. Periodic reconciliation also finishes sales
whose ledger settled by callback but whose stock handover was interrupted.

Integrated card returns are blocked unless that tenant's verified procedure
sets `manual_refunds: true` for an external original-provider terminal refund.
The operator must still record a distinct refund approval reference and obtain
independent approval. A collection fallback does not enable refunds. Automated
provider refunds and Daraja reversals require their provider-specific adapters
and evidence before activation; an internal reversal cannot substitute for a
provider refund.

Leave `enabled` and `validated` false until the tenant's provider credentials,
terminal/account identifiers, callback or polling route, idempotency behaviour,
status mapping, amount/currency checks, duplicate delivery handling, timeout
recovery and return/refund procedure have been verified in that provider's
sandbox. A registered adapter is required before an integration can appear
ready. Daraja remains unavailable until its credentials and sandbox evidence are
provided. These settings prepare tenant-isolated connections; they do not claim
live card terminal, Daraja or VSCU certification.

Remote VSCU endpoints require HTTPS. In Docker, loopback is the container;
provide a reachable authenticated server-side endpoint for the registered device.
Do not set `validated` until sandbox/device evidence, provider reconciliation,
fiscal item/tax mappings, fiscal receipt formatting and printer checks pass.
Celery beat schedules provider reconciliation and fiscal processing every minute.

Implementation follows the [KRA VSCU v2 specification](https://www.kra.go.ke/images/publications/VSCU_Specification_Document_v2.0.pdf),
including `/trnsSales/saveSales` and original-invoice-linked credit notes.
