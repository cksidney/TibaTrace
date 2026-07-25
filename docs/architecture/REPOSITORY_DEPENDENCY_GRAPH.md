# DawaTrace Repository Architecture & Dependency Graph

## Executive Overview

DawaTrace is Esenai Group Ltd's standalone enterprise pharmacy platform and intelligent clinical point-of-sale (POS) system. It is designed as a strict, tenant-isolated modular monolith.

This document establishes the authoritative application dependency graph, domain boundaries, single sources of truth, state machines, and contract mapping rules across the repository.

---

## 1. Backend Application Dependency Graph (`backend/apps/`)

```mermaid
graph TD
    %% Core Infrastructure & Tenancy
    platform[apps.platform] --> tenancy[apps.tenancy]
    identity[apps.identity] --> tenancy
    organizations[apps.organizations] --> tenancy
    audit[apps.audit] --> tenancy

    %% Procurement, Supplier Governance & Inventory
    procurement[apps.procurement] --> tenancy
    procurement --> medicines
    procurement --> organizations
    inventory[apps.inventory] --> tenancy
    inventory --> medicines
    inventory --> procurement

    %% Customers, Sales & Fulfilment
    customers[apps.customers] --> tenancy
    customers --> organizations
    customers --> medicines
    sales[apps.sales] --> tenancy
    sales --> customers
    sales --> medicines
    sales --> inventory
    sales --> organizations

    %% Clinical Core & Enterprise Medicine Master
    patients[apps.patients] --> tenancy
    practitioners[apps.practitioners] --> tenancy
    medicines[apps.medicines] --> tenancy
    medicines --> organizations
    clinical[apps.clinical] --> tenancy
    clinical --> patients
    clinical --> practitioners

    %% Prescription & CDS
    cds[apps.cds] --> tenancy
    cds --> medicines
    prescription[apps.prescription] --> tenancy
    prescription --> patients
    prescription --> practitioners
    prescription --> medicines
    prescription --> cds
    prescription --> clinical
    prescription --> inventory
    prescription --> sales
    prescription --> documents
    prescription --> workflows
    prescription --> notifications
    prescription --> audit

    %% POS Clinical Screening Components
    pos_screening_models[apps.cds.pos_screening_models] --> cds
    pos_screening_models --> patients
    pos_screening_models --> prescription
    pos_screening_models --> tenancy
    pos_screening_services[apps.cds.pos_screening_services] --> pos_screening_models
    pos_screening_services --> cds_services[apps.cds.services]
    pos_screening_services --> medicines
    pos_screening_services --> patients
    pos_screening_services --> inventory
    pos_api[apps.cds.pos_api] --> pos_screening_services
    pos_api --> pos_screening_models

    %% FHIR & Terminology
    terminology[apps.terminology] --> tenancy
    fhir[apps.fhir] --> tenancy
    fhir --> clinical
    fhir --> prescription
    fhir --> terminology

    %% Auxiliary & Integration
    crosswalks[apps.crosswalks] --> tenancy
    documents[apps.documents] --> tenancy
    workflows[apps.workflows] --> tenancy
    notifications[apps.notifications] --> tenancy
```

### Module Responsibilities & Boundary Invariants

1. **`apps.tenancy` / `apps.identity` / `apps.organizations`**:
   - Authoritative for tenant resolution, identity federation, user roles, and organization structures.
   - Every domain query is tenant-qualified via `StrictTenantManager`.

2. **`apps.clinical` & `apps.patients` / `apps.practitioners`**:
   - Centralized boundary for clinical data integrity.
   - Enforces same-tenant/same-patient invariants, immutable ownership, document hashes, and temporal consistency.

3. **`apps.prescription` & `apps.cds`**:
   - Own the legal-validation, versioned DUR, pharmacist-review, immutable verification, dispensing, supply, medication-history, reversal, and patient-return lifecycles.
   - `apps.prescription` consumes, but never duplicates, medicine, inventory reservation, FEFO, ledger, sales, document, workflow, notification, identity, and audit authorities.
   - Inventory is reduced only by `InventoryLedgerService` at final supply. Preparation and allocation do not reduce on-hand stock.
   - Prescriptions cannot reserve stock without current pharmacist verification.
   - POS clinical screening modules (`apps.cds.pos_screening_models`, `apps.cds.pos_screening_services`, `apps.cds.pos_api`) integrate POS clinical workflows directly with the central CDS engine.

4. **`apps.fhir` & `apps.terminology`**:
   - HL7 FHIR R4 4.0.1 gateway mapping domain models to/from FHIR resource representations.
   - Terminology service managing code systems, value sets, and concept validations.

5. **`apps.crosswalks` & `apps.documents`**:
   - Legacy system identifier mapping and document encryption/storage.

---

## 2. Shared Packages & Frontend Workspaces

```mermaid
graph LR
    subgraph Packages
        shared["@dawatrace/shared (packages/shared)"]
        shared_clinical["packages/shared/src/clinical"]
    end

    subgraph Applications
        hq["DawaTrace HQ Admin Shell (apps/hq)"]
        portal["Patient/Provider Portal (apps/portal)"]
        pos_android["Android POS (apps/pos-android)"]
        pos_windows["Windows POS (apps/pos-windows)"]
        pos_win_plugin["apps/pos-windows/plugins/drug-interaction"]
        pos_and_plugin["apps/pos-android/plugins/drug-interaction"]
    end

    hq --> shared
    portal --> shared
    pos_android --> shared
    pos_windows --> shared
    shared_clinical --> shared
    pos_win_plugin --> shared_clinical
    pos_and_plugin --> shared_clinical
```

* **`@dawatrace/shared`**: The single source of truth for TypeScript interfaces, API contract definitions, FHIR types, and domain status enums.
* **`packages/shared/src/clinical`**: Shared clinical contracts consumed by POS drug interaction plugins.
* **Frontend Applications & Plugins**: Consume `@dawatrace/shared` contracts directly. `apps/pos-windows/plugins/drug-interaction` and `apps/pos-android/plugins/drug-interaction` consume `packages/shared/src/clinical`. No ad-hoc or duplicated type definitions are permitted.

---

## 3. Authoritative State Machine Specifications

### Prescription Lifecycle State Machine (`apps.prescription`)

```text
DRAFT -> CLINICAL_REVIEW -> APPROVED / BLOCKED -> DISPENSING
      -> READY_FOR_PAYMENT -> PAID -> DISPENSED -> REVERSED
```

- **Invariant**: Legacy workflow transitions use `PrescriptionWorkflowService`; Phase 5 legal, clinical, verification, dispensing, supply, reversal, and return transitions use their authoritative domain services. Serializers and ViewSets never mutate these states directly.
- **Payment & Dispensing Separation**: Payment completion (`PAID`) and physical dispensing completion (`DISPENSED`) remain separate, auditable domain states.

The legacy state machine remains available for existing clients. Phase 5 adds orthogonal legal-validation, clinical-review, pharmacist-verification, and dispensing state dimensions governed by services in `apps.prescription.services.clinical_dispensing`.

```text
Prescription Received
→ Legal Validation
→ Versioned DUR
→ Pharmacist Review / Intervention
→ Immutable Pharmacist Verification
→ Inventory Reservation
→ Existing FEFO Allocation
→ Preparation
→ Independent Check
→ Counselling
→ Supply / Inventory Issue
→ Append-only Medication History
```

---

## 4. Architectural Rules & Governance

1. **No Live External Dependencies**: DawaTrace must remain completely runnable without Mercato-OS databases, APIs, or queues.
2. **Contract-First Changes**: Model or serializer changes must simultaneously update backend serializers, tests, shared TS interfaces (`packages/shared`), and API clients.
3. **Append-Only Clinical Audit**: All clinical reviews, CDS overrides, and status transitions generate immutable, actor-attributed audit records.
