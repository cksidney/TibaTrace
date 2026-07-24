# Dispensing Reversals and Returns

## Reversal

`DispensingReversalService` requires a reason, authorized actor, original supply line, positive quantity within the original supply, physical-return indicator, condition, inventory eligibility, and idempotency key.

A reversal appends a uniquely sourced `REVERSED` medication-history record and emits `DispensingReversed`. Multiple bounded partial reversals are supported. The net clinical supply projection is reduced so a corrected supply can be authorized, while the original supply, issue, and medication history remain immutable.

Reversal approval requests open the `REVERSAL_APPROVAL` queue. Approval closes it and creates a protected reversal record. No inventory entry is posted automatically; physical stock must enter the patient-return and quality process.

## Patient Return

Returns reference the original supply, patient, exact line and batch, quantity, condition, reason, receiver, and a tenant-owned quarantine or returns location. Cumulative returns cannot exceed supply.

Inspection records a quality decision, inspector, time, destruction path, and refund eligibility. The receiver cannot solely approve saleable restock, and even an eligibility decision does not create an inventory movement. An explicit inventory quality/re-entry process remains required.

Receipt opens a branch-scoped inspection queue, generates a patient-return receipt, and creates a non-sensitive outbox notification. Inspection closes the queue.
