# Controlled Medicines

Controlled workflows apply additional configured controls without asserting jurisdiction-specific law:

- verified patient identifier;
- original prescription or signature evidence;
- verified prescriber with controlled authority;
- controlled-verification actor capability;
- controlled-capable inventory location;
- exact batch traceability;
- independent final check and separate supply actor;
- immutable controlled-register domain event;
- enhanced reversal and return capability checks.

`ControlledMedicineSupplied` includes tenant, patient identifier reference, prescriber, prescription, medicine, SKU, batch, quantity, unit, pharmacist, supply date, category, correlation metadata, and inventory-issue reference. It does not maintain an editable running stock balance.

Returned or reversed controlled medicine is never automatically restored to saleable stock.
