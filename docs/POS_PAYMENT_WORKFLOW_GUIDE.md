# POS payment workflow

> **Superseded by [the TibaTrace End-to-End Guide](TIBATRACE_USER_GUIDE.md) — §4.2 Dispensing a prescription — payment.**
>
> Kept for its engineering detail and history. The guide is authoritative
> for how the system is used; where the two disagree, the guide is right.

**Current release decision:** `POS_UI_UX_BLOCKED`

This guide describes the payment paths that are safe to operate today. It is
not a claim that M-PESA, split tender, receipt printing or payment recovery is
complete.

## Authority boundary

The native dispensing command at
`POST /api/pos/dispensing/episodes/{episode_id}/process-payment/` is a
compatibility adapter. It does not write `DispensingEpisode.payment_state` as a
client success flag. For a cash or manual-card settlement it:

1. locks the episode and checks the clinical-ready state;
2. resolves the assigned open register, open business day and accountable
   operator shift from the device identifier;
3. reads the total from the linked `SalesOrder` rather than trusting the
   amount posted by the client;
4. creates an idempotent `PaymentIntent`, `PaymentTender` and immutable
   `PaymentSettlement` record;
5. projects `DispensingEpisode.payment_state` from those ledger facts; and
6. moves the dispensing lifecycle to `PAID` only after the projection confirms
   that the whole patient-payable balance is settled.

The `PaymentTender` holds the authoritative register session and operator shift
for reconciliation. A retry of the same idempotency key returns the original
settlement even if the register has since closed; it never creates a second
charge.

## Supported native actions

| Tender | Native status | Rules |
| --- | --- | --- |
| Cash | Available | Amount tendered is validated; change is calculated and stored on the server. |
| Card (manual approval) | Available | The amount must equal the authoritative outstanding balance and an approval reference is mandatory. |
| M-PESA | Disabled | A reference or STK acknowledgement cannot settle an episode. A provider-confirmed staged workflow is still required. |
| Split tender | Disabled | The server ledger supports allocations, but the native authoritative allocation editor is not yet implemented. |
| Zero patient-payable | Blocked | There is no completed insurance/receivable and zero-balance completion workflow in this native path. |

## Operator recovery

- If cash or card submission has an unknown network outcome, do not submit a
  new payment. Refresh the episode and use the original idempotency key only
  when the client can safely retry the same command.
- A partial, pending, reversed or status-unknown provider tender must not
  release medicine. The payment-state projection is the commercial supply gate.
- A card terminal acceptance is not an approval until the operator enters the
  terminal approval reference and the server records the immutable settlement.

## Evidence and remaining closure

`backend/tests/test_pos_payment_ledger.py` plus direct-dispensing regression
tests cover cash settlement, manual card settlement, split allocation at the
ledger layer, duplicate callbacks, duplicate cash submission, pricing refusal,
register/shift binding and staged M-PESA refusal.

Completion still requires a production M-PESA adapter with governed status
reconciliation, the native split-tender editor, insured/zero-payable handling,
receipt snapshots and durable print jobs, Sync Centre recovery, visual review
and physical hardware evidence. Until then the POS decision remains
`POS_UI_UX_BLOCKED`.
