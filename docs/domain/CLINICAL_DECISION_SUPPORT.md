# Clinical Decision Support

## Versioned Knowledge

`ClinicalKnowledgeRelease` identifies source, source version, licence, effective period, classification, and checksum. `ClinicalKnowledgeRule` records a stable rule ID and version. Tenant-specific active releases take precedence over global releases.

## Evaluation

`ClinicalDecisionSupportService` creates a context hash over patient, prescriber, dates, controlled and repeat flags, and material prescription-item instructions. Findings preserve rule version, source, evidence, explanation, recommendation, severity, item, medicine, factor, resolution, resolver, reason, and time.

Provider failure and unavailable knowledge fail closed as `ERROR` and `KNOWLEDGE_UNAVAILABLE`. They are never represented as a pass.

## Configurability

The local provider supports configured interaction, allergy, duplication, contraindication, age, weight, dose, frequency, duration, renal, hepatic, pregnancy, lactation, controlled-medicine, repeat, and formulary checks. Missing required age, weight, or special-population data emits `INSUFFICIENT_DATA`.

Ingredient context is expanded per prescription item, so two items containing the same ingredient produce duplicate-therapy evidence while a single rule issue remains deduplicated within its evaluation. Critical findings open a role-aware queue and must be resolved or validly overridden before review completion.

Rules and seed content are marked demonstration-only. Deployment-specific clinical content must be licensed, reviewed, versioned, and activated separately.
