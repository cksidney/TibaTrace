# POS Clinical Integrity

The clinical integrity verification system detects and repairs data anomalies, state mismatches, and audit gaps in POS clinical screening records.

## Management Command

Integrity checks are executed via the Django management command:
```bash
python manage.py check_pos_clinical_integrity [--repair] [--tenant-id=<UUID>]
```

## Violation Types Detected (10 Categories)

1. **Unlinked Override**: Override record lacking corresponding pharmacist review.
2. **Missing Justification**: High/Critical override without mandatory text rationale.
3. **Invalid Actor**: Overriding user missing required clinical capabilities.
4. **Self-Review Violation**: Cashier user matches reviewing pharmacist user.
5. **Hash Mismatch**: Context hash does not match computed transaction payload.
6. **Orphan Audit Event**: `PosClinicalAuditEvent` missing parent screening reference.
7. **Unsynced Offline Decision**: Offline decision pending past sync threshold.
8. **Controlled Medicine Bypass**: Controlled item completed without required checks.
9. **Tampered Package Signature**: Offline rules bundle with invalid HMAC signature.
10. **State Projection Desync**: Denormalized clinical status out of sync with event ledger.

## Repair Mode Policy

- **Read-Only Default**: By default, the command reports violations without modifying database state.
- **Projection Rebuild**: When `--repair` is passed, repair mode rebuilds read projections and audit linkages.
- **Strict Invariant**: Repair mode **never fabricates** clinical decisions, pharmacist signatures, or override justifications.
