# Pharmacist Interventions

`PharmacistIntervention` preserves the prescription, item, review, finding, intervention type, contacted party and method, request, response, original instruction, revised instruction, prescriber authorization, outcome, actor, supporting document, status, and timestamps.

`PharmacistInterventionService` creates and resolves interventions. Open or awaiting-response interventions block an approving clinical-review outcome and pharmacist verification.

The supported intervention types are clarification, dose, medicine, duration, frequency, or form change, substitution approval, medicine stop, counselling-only, and other.

Clarification work items are tenant- and branch-scoped. Resolution closes the corresponding queue and emits `PrescriberClarificationReceived`.
