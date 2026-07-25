# POS Clinical RBAC Matrix

Role-Based Access Control (RBAC) rules governing clinical screening, pharmacist review, overrides, configuration, and auditing at POS terminals.

## Capability Matrix

| Capability | Cashier | Pharmacy Assistant | Pharmacist | Clinical Admin | Auditor |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `pos.clinical_screening.view` | Yes | Yes | Yes | Yes | Yes |
| `pos.clinical_alert.dismiss_low` | Yes | Yes | Yes | Yes | No |
| `pos.pharmacist_review.request` | Yes | Yes | Yes | Yes | No |
| `pos.pharmacist_review.perform` | No | No | Yes | Yes | No |
| `pos.clinical_override.low` | No | No | Yes | Yes | No |
| `pos.clinical_override.moderate` | No | No | Yes | Yes | No |
| `pos.clinical_override.high` | No | No | Yes | Yes | No |
| `pos.clinical_override.critical` | No | No | No | Yes | No |
| `pos.clinical_config.manage` | No | No | No | Yes | No |
| `pos.clinical_audit.view` | No | No | Yes | Yes | Yes |

## Enforcement Invariants

- **Cashier Limits**: Cashiers may view alerts and request pharmacist reviews, but cannot execute overrides.
- **Pharmacist Scope**: Pharmacists can perform reviews and override alerts up to `HIGH` severity.
- **Critical & Admin Scope**: Overriding `CRITICAL` findings requires Clinical Admin privileges when explicitly configured.
