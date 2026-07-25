# POS Clinical Override Policy

The clinical override policy governs under what circumstances clinical alerts can be bypassed at the point of sale.

## Override Requirements

Every clinical override recorded at POS must contain:
- **Pharmacist Identity**: Authenticated user ID of the overriding pharmacist.
- **Structured Reason**: Selected standard override category.
- **Clinical Justification**: Mandatory rationale explaining clinical safety assessment.

## Structured Override Reasons

Standard override reasons range from `KNOWN_AND_MONITORED` through `BENEFIT_OUTWEIGHS_RISK`, `PATIENT_TOLERATING`, `PRESCRIBER_CONSULTED`, `FALSE_POSITIVE_RULE`, and `OTHER`.

## Severity & Capability Matrix

- **`override_low`**: Permits bypassing low-severity informational alerts.
- **`override_moderate`**: Permits bypassing moderate-severity clinical warnings.
- **`override_high`**: Permits bypassing high-severity safety alerts (requires mandatory free-text justification).
- **`override_critical`**: Permits bypassing critical contraindication alerts (disabled by default across system configurations; requires mandatory free-text justification and supervisor approval when enabled).

## Policy Safeguards

- Free-text clinical justification is strictly mandatory for `HIGH` and `CRITICAL` alert overrides.
- `CRITICAL` severity overrides remain globally disabled by default to protect patient safety.
