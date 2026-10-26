# TibaTrace solution classification — provisional for DHA confirmation

**Updated:** 26 October 2026<br>
**Production server baseline:** `1.0.0-rc71`, commit `2965194a29311314e8a5772adfeee5af8c14a8f2`<br>
**Decision authority:** Kenya Digital Health Agency (DHA)<br>
**Status:** Internal description only; no DHA category determination is attached. The system DPIA remains **NOT APPROVED**.

## Product description for category discussion

TibaTrace is a multi-tenant pharmacy operations and clinical dispensing platform with HQ web, Windows/Android POS, patient and prescription workflows, stock and sales management, and integration scaffolding. It is designed for clinical and pharmacy use. The audited server release is rc71; installed native-client versions were not verified. DHA, HIE, RX and checkout activation paths were disabled in the reviewed production configuration.

## Questions to resolve with DHA

Ask DHA to determine the applicable system category or categories for the actual intended use. Pharmacy-system classification is the primary question. Ask whether any EMR/HIS or other category applies to the specific patient, prescription, dispensing or exchange features. Provide the current architecture, data flows, production version, deployment locations, intended facilities and integrations; do not self-assign an official category from this note.

The owner states the product is DHA certified. This file does not verify that statement. Obtain the certificate and confirm named product/operator, category, assessed version, dates, conditions, approved interfaces and facility/production scope. If any information differs, ask DHA to resolve it in writing before representing the scope.

## Evidence to take to the classification review

- [System architecture](../system/03_SYSTEM_ARCHITECTURE.md), [technical specification](../system/05_TECHNICAL_SPECIFICATIONS.md) and exact release identity.
- [System DPIA](../system/01_DATA_PROTECTION_IMPACT_ASSESSMENT.md), currently NOT APPROVED, with [remaining closure plan](../system/24_DPIA_REMAINING_ACTION_PLAN_2026-10-26.md).
- [DHA evidence register](DHA_DOCUMENT_EVIDENCE_REGISTER.md), with certificate/reference verification still outstanding.
- [Current traceability matrix](TIBATRACE_DHA_TRACEABILITY_MATRIX.md), which identifies evidence gaps and does not claim criterion-level compliance.

Recheck the official [DHA certification guide](https://certification.dha.go.ke/regulatory-guide) and [system categories](https://certification.dha.go.ke/systems) at the time of submission. This provisional description is not a DHA ruling or certification claim.
