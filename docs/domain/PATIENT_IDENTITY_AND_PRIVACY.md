# Patient Identity and Privacy

## Boundary

`apps.patients` owns tenant-scoped patient demographics, protected identifiers, allergies, condition summaries, current medication statements, and the bounded clinical safety summary. It is not a full electronic medical record.

## Identity Controls

- Patient numbers and non-empty external references are unique inside a tenant.
- Sensitive identifier values are normalized, encrypted with a tenant-derived Fernet key, and stored separately from a keyed SHA-256 lookup digest.
- Routine serializers expose only identifier type, verification metadata, and the final four characters.
- Full identifier access requires `patients.identity.view` or `patients.sensitive.view`, a reason, and an immutable audit event.
- Cross-tenant relations are rejected by model validation and tenant-qualified APIs.

## Least Privilege

Users without `patients.sensitive.view` receive `null` for contact, address, emergency-contact, caregiver, and record-restriction fields. Users without `patients.identity.view` do not receive identifier records or the external patient reference.

## Clinical Summary

The summary records pregnancy, lactation, renal and hepatic indicators, height, weight, source, verification state, verifier, and verification time. `NOT_RECORDED` is an explicit state and is not treated as absence of risk.

Medication history is owned by the dispensing workflow and is append-only. Reversals and patient returns add history entries rather than rewriting the original supply record.
