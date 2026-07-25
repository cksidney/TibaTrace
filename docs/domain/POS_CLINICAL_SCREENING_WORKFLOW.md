# POS Clinical Screening Workflow

The clinical screening workflow automatically evaluates transactions at the point of sale against central CDS safety rules.

## Execution Triggers

Screening evaluates automatically upon any of the following events:
- **Basket Change**: Addition, removal, or quantity update of any medication item.
- **Patient Change**: Attachment, removal, or switching of the active patient profile.
- **Prescription Change**: Attachment, detachment, or editing of an associated prescription.
- **Proceed to Payment**: Final checkout attempt prior to opening the payment gateway.
- **Resume Transaction**: Resuming a held or suspended transaction.

## Context Hash & Optimization

- **Context Hash**: A cryptographic hash computed over the transaction context prevents redundant CDS rule evaluations when context remains unchanged.
- **Cache Strategy**: Identical context hashes reuse existing screening results from `ClinicalScreeningCache`.

## Clinical Context & Categories

- **Screening Context**: Includes current basket lines (SKUs, active ingredients, dosages), patient allergies, recent medication history, and relevant clinical summary indicators.
- **Finding Coverage**: Classifies findings across 26 distinct clinical categories (e.g., drug-drug interactions, drug-allergy alerts, therapeutic duplication, contraindications, dosage limits, renal/hepatic adjustments).
