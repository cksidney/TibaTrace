# Drug Utilization Review

## Supported Categories

The rule catalogue supports drug-drug interaction, duplicate therapy, allergy, contraindication, dose high/low, frequency high/low, duration high/low, age, weight-based dose, renal, hepatic, pregnancy, lactation, controlled-medicine, early/late repeat, therapeutic duplication, formulary restriction, maximum daily dose, and insufficient data.

## Context

Screening considers current prescription ingredients and confirmed or suspected active allergies. Rule criteria can use dose, daily frequency, duration, age, weight, pregnancy, lactation, renal and hepatic status, controlled flags, and refill dates.

## Resolution

Findings remain visible after resolution. Critical or legacy `BLOCK` findings prevent review completion until resolved, marked not applicable, or overridden by an authorized actor. Evaluation evidence itself is immutable; resolution is recorded on the finding and in a separate immutable override where applicable.

Duplicate issue keys use evaluation, rule ID/version, prescription item, and interacting factor.
