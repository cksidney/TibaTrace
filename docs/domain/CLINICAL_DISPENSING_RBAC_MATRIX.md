# Clinical Dispensing RBAC Matrix

| Action | Capability | Segregation |
|---|---|---|
| Create patient | `patients.create` | Tenant scoped |
| Manage / reveal identity | `patients.identity.manage` / `patients.identity.view` | Reveal requires reason and audit |
| View sensitive patient data | `patients.sensitive.view` | Masked by default |
| Record allergy / summary | `patients.allergy.record` / `patients.clinical_summary.manage` | Provenance required |
| Verify prescriber | `prescribers.verify` | Invalid licence cannot be approved |
| Receive prescription | `prescriptions.intake` | Cannot create clinical approval |
| Legal validation | `prescriptions.legal_validate` | Findings are preserved |
| Clinical review | `prescriptions.clinical_review` | Current context required |
| Create intervention | `prescriptions.intervention.create` | Open work blocks verification |
| Override critical finding | `prescriptions.critical_override` | Reason and justification required |
| Pharmacist verification | `prescriptions.pharmacist_verify` | Non-pharmacist capability denied |
| Controlled verification | `prescriptions.controlled_verify` | Additional identity, prescriber, custody checks |
| Approve substitution | `prescriptions.substitution.approve` | Policy approvals enforced |
| Reserve / allocate | `dispensing.reserve` / `dispensing.allocate` | Verified prescription only |
| Prepare | `dispensing.prepare` | Exact SKU and batch |
| Final check | `dispensing.check` | Preparer cannot self-check |
| Counsel | `dispensing.counsel` | Required counselling or refusal |
| Supply | `dispensing.supply` | Payment, verification, check, and batch gates |
| Authorize repeat exception | `dispensing.repeat.authorize` | Normal interval remains default |
| Reverse | `dispensing.reverse` | No automatic stock return |
| Receive / inspect return | `dispensing.return.receive` / `dispensing.return.quality` | Receiver cannot solely approve restock |

Legacy capability aliases remain for existing Phase 1–4 roles, while new roles should use the explicit Phase 5 capabilities.

The clinical work-queue endpoint is authenticated and tenant-scoped, then filters each row by `required_capability`. Optional `branch_ids` user metadata further narrows visibility before request-level branch filters are applied.
