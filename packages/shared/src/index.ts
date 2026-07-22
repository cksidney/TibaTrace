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

export type ClinicalProductStatus =
  | "DRAFT"
  | "UNDER_REVIEW"
  | "ACTIVE"
  | "SUSPENDED"
  | "RETIRED";

export type ManufacturedProductStatus =
  | "DRAFT"
  | "REGISTERED"
  | "ACTIVE"
  | "SUSPENDED"
  | "WITHDRAWN"
  | "DISCONTINUED";

export type CommercialSKUStatus =
  | "DRAFT"
  | "ACTIVE"
  | "INACTIVE"
  | "DISCONTINUED"
  | "RECALLED";

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

export interface DoseFormDTO {
  id: string;
  code: string;
  name: string;
  description?: string;
  isActive: boolean;
}

export interface ActiveSubstanceDTO {
  id: string;
  code: string;
  canonicalName: string;
  displayName: string;
  substanceType: string;
  controlledClassification: string;
  status: string;
}

export interface IngredientCompositionDTO {
  id: string;
  clinicalProductId: string;
  activeSubstanceId: string;
  activeSubstanceName: string;
  numeratorValue: number;
  numeratorUnit: string;
  denominatorValue: number;
  denominatorUnit: string;
  sequence: number;
}

export interface ClinicalMedicinalProductDTO {
  id: string;
  code: string;
  canonicalName: string;
  doseForm: string;
  prescriptionClassification: string;
  controlledClassification: string;
  status: ClinicalProductStatus;
  ingredients: IngredientCompositionDTO[];
}

export interface ManufacturedMedicinalProductDTO {
  id: string;
  code: string;
  brandName: string;
  clinicalProductId: string;
  manufacturerId?: string;
  status: ManufacturedProductStatus;
}

export interface CommercialSKUDTO {
  id: string;
  skuCode: string;
  displayName: string;
  manufacturedProductId: string;
  defaultBarcode?: string;
  isSaleable: boolean;
  isPurchasable: boolean;
  isDispensable: boolean;
  status: CommercialSKUStatus;
}
