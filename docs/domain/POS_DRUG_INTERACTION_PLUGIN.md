# POS Drug Interaction Plugin

The POS Drug Interaction Plugin embeds real-time clinical decision support directly into point-of-sale transaction workflows across POS clients.

## Architecture & Design Principles

- **Centralized Engine**: The plugin consumes the central CDS engine (`apps.cds`), ensuring zero duplicate rule logic across web, mobile, and desktop applications.
- **Client Endpoints**: Integrates via backend endpoints served under `/api/pos/clinical-screening/`.
- **Plugin Governance**: Feature availability and operational behavior are dynamically controlled by `DrugInteractionPluginConfig`.
- **Shared Contracts**: Uses shared TypeScript contracts (`@dawatrace/shared/src/clinical`) between Windows (`apps/pos-windows`) and Android (`apps/pos-android`) frontends.

## Core Plugin Components

- **TransactionClinicalContextBuilder**: Assembles current basket, patient context, and medication history into screening requests.
- **ClinicalScreeningClient**: Communicates with central screening APIs with fallback mechanisms.
- **InteractionResultStore**: Stores active screening results, severity scores, and finding categories.
- **ClinicalAlertPresenter**: Manages UI alert displays and cashier notifications.
- **PharmacistReviewWorkflow**: Coordinates cashier escalation and pharmacist review sessions.
- **ClinicalOverrideWorkflow**: Captures structured override reasons and mandatory justifications.
- **OfflineClinicalSafetyGuard**: Enforces safety policies and offline screening package evaluation when disconnected.
- **ClinicalAuditPublisher**: Publishes immutable clinical audit events (`PosClinicalAuditEvent`).
- **ClinicalScreeningCache**: Caches context hashes and evaluation responses for performance.
