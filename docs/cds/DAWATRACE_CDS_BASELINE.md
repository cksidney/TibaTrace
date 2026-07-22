# DawaTrace CDS and Drug Interaction Baseline

## Canonical Engine

`ClinicalDecisionSupportService` builds patient/prescription context, chooses the
active tenant knowledge release before an explicitly global fallback, invokes a
`ClinicalKnowledgeProvider`, and stores an evaluation plus source-attributed
findings. It does not perform generic indirect ORM persistence for clinical
resources.

The provider contract includes drug-drug, allergy, duplicate therapy, condition,
age, pregnancy, renal, hepatic, dose, and duration checks. Each finding carries
rule ID/version, source/version, effective date, severity, evidence, explanation,
recommended action, override policy, affected medicine, interacting factor,
tenant, patient, prescription, and timestamp through its persisted context.

## Outcomes

- `PASS`: active knowledge ran and produced no warning/block finding.
- `WARNING`: reviewable finding exists.
- `BLOCK`: blocking finding exists.
- `KNOWLEDGE_UNAVAILABLE`: no active in-date knowledge release exists.
- `ERROR`: the provider failed.

Unavailable/error can never become pass. A stale clinical context hash blocks
progress after prescription changes.

## Overrides

Overrides require `cds.override` and a non-empty reason. A `PROHIBITED` finding is
not overrideable. The authorized user, finding, prescription, tenant, reason, and
time are persisted.

## Content Governance

Knowledge releases require source, source version, licence, effective date,
checksum, and content classification. Phase 2 includes only test/demonstration
content created by tests. No unlicensed production medical advice or commercial
interaction dataset is included.

## Evidence and Limits

Focused CDS/prescription tests cover tenant/global manager behavior and precedence,
missing knowledge, empty release pass, source-attributed drug interaction,
allergy, duplicate therapy, provider failure, override authorization, workflow,
stale context, dispense idempotency, and cross-tenant rejection.

The local provider has deterministic demonstration logic. Validated licensed
rules, clinical governance sign-off, performance testing at production rule
volume, and regulatory validation remain external gates.
