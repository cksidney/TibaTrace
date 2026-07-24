# Partial and Repeat Dispensing

Supply lines record supplied quantity, outstanding authorized quantity, partial reason, and next eligible date. Partial supplies create a follow-up work item and a notification containing only the prescription reference and date.

Each subsequent supply locks the prescription item and reconciles cumulative quantity against:

- quantity per issue;
- authorized repeats;
- quantity already supplied;
- prepared quantity;
- exact reservation and batch;
- earliest and latest refill dates.

`quantity_supplied_total` is the net clinical supply projection: gross immutable supply lines minus authorized reversal quantities. Completed repeat cycles decrement item and prescription `repeats_remaining`; configured minimum intervals set the next earliest refill date. Full issue cycles open a repeat-due queue, while an incomplete issue opens the distinct partial-follow-up queue.

Supported partial reasons include stock, patient request, clinical or controlled limits, pack size, payment, clarification, and other. The service never exceeds `quantity × (refills authorized + 1)`.
