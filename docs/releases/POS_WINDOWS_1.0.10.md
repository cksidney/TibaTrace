# Windows POS 1.0.10 — build 10

Adds ledger-backed clinical/retail split checkout, exact cash change, external
card approval references, recoverable interrupted commands, original-method
refunds and supervised unfinished-payment voids. VSCU evidence has separate
invoice/credit-note and print states. M-PESA stays disabled until supplied API
credentials and provider validation are in place. TibaTrace icons remain in the
executable, installer and shortcuts. Install the signed managed package on each
till to use the new screens; server deployment does not update installed tills.

No automatic card-terminal protocol is claimed. No card/PIN data is collected.
Physical printer and live provider/device certification require on-site checks.

Requires the rc52 payment backend. The final checkout review also prevents a
zero balance without a positive settled ledger entry from showing “Payment
settled,” and presents readable refusal and unknown-outcome messages. Native
checkout regression coverage: 121 passing tests.
