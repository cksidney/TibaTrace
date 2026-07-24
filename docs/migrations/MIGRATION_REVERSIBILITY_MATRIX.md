# Migration Reversibility Matrix

| Phase | Applications | Head migrations | Rollback target | Data-loss boundary | Validation |
|---|---|---|---|---|---|
| Phase 1–4 | Existing platform through sales | Existing committed heads | Not changed by Phase 5 | Existing policy | Full repository validation |
| Phase 5 patient master | `patients` | `0002` | `patients.0001` | Drops Phase 5 patient summary and added identity metadata | Zero-to-head, rollback, reapply |
| Phase 5 prescriber governance | `practitioners` | `0002` | `practitioners.0001` | Drops Phase 5 authority and verification metadata | Zero-to-head, rollback, reapply |
| Phase 5 DUR | `cds` | `0006` | `cds.0004` | Drops Phase 5 finding resolution and override metadata | Zero-to-head, rollback, reapply |
| Phase 5 dispensing | `prescription` | `0006` | `prescription.0002` | Drops Phase 5 dispensing, supply, history, reversal, return, work-item, verification, and stored label-document links | Zero-to-head, rollback, reapply |

All Phase 5 schema operations are Django-reversible. Rollback is a deployment operation that intentionally removes Phase 5 data; it is not a clinical-record deletion workflow and must not be used against production data without an approved backup and migration plan.
