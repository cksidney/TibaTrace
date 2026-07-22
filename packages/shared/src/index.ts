export const DAWATRACE_FHIR_VERSION = "4.0.1" as const;

export type DawaTracePrescriptionState =
  | "DRAFT"
  | "CLINICAL_REVIEW"
  | "BLOCKED"
  | "APPROVED"
  | "DISPENSING"
  | "READY_FOR_PAYMENT"
  | "PAID"
  | "DISPENSED"
  | "REVERSED";

export type ClinicalDecisionStatus =
  | "PASS"
  | "WARNING"
  | "BLOCK"
  | "KNOWLEDGE_UNAVAILABLE"
  | "ERROR";

export interface TenantContext {
  tenantId: string;
  correlationId: string;
}

export interface ClinicalSourceAttribution {
  ruleId: string;
  ruleVersion: string;
  source: string;
  sourceVersion: string;
  effectiveDate: string;
}
