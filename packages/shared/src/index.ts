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

export type SupplierStatus =
  | "PROSPECTIVE"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "ACTIVE"
  | "SUSPENDED"
  | "DISQUALIFIED"
  | "ARCHIVED";

export type PurchaseRequisitionStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "PARTIALLY_ORDERED"
  | "FULLY_ORDERED"
  | "REJECTED"
  | "CANCELLED"
  | "CLOSED";

export type PurchaseOrderStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "APPROVED"
  | "SENT"
  | "ACKNOWLEDGED"
  | "PARTIALLY_RECEIVED"
  | "FULLY_RECEIVED"
  | "CLOSED"
  | "CANCELLED"
  | "REJECTED";

export type GoodsReceiptStatus =
  | "DRAFT"
  | "RECEIVING"
  | "RECEIVED"
  | "UNDER_INSPECTION"
  | "PARTIALLY_ACCEPTED"
  | "ACCEPTED"
  | "REJECTED"
  | "CLOSED"
  | "CANCELLED";

export type BatchQualityStatus =
  | "PENDING_INSPECTION"
  | "QUARANTINED"
  | "RELEASED"
  | "REJECTED"
  | "RETURN_PENDING"
  | "RETURNED"
  | "DESTROYED";

export interface SupplierDTO {
  id: string;
  supplierCode: string;
  legalName: string;
  tradingName?: string;
  registrationNumber?: string;
  taxIdentifier?: string;
  country: string;
  paymentTerms: string;
  defaultCurrency: string;
  status: SupplierStatus;
  riskCategory: string;
}

export interface PurchaseRequisitionDTO {
  id: string;
  requisitionNumber: string;
  requestingBranch: string;
  requester: string;
  requestedDeliveryDate: string;
  priority: string;
  status: PurchaseRequisitionStatus;
}

export interface PurchaseOrderDTO {
  id: string;
  poNumber: string;
  supplierId: string;
  orderingBranch: string;
  orderDate: string;
  expectedDeliveryDate: string;
  currency: string;
  totalGross: number;
  revisionNumber: number;
  status: PurchaseOrderStatus;
}

export interface GoodsReceiptDTO {
  id: string;
  grnNumber: string;
  purchaseOrderId: string;
  supplierId: string;
  receivingBranch: string;
  deliveryNoteNumber: string;
  arrivalTime: string;
  status: GoodsReceiptStatus;
}

export interface ReceivedBatchDTO {
  id: string;
  grnLineId: string;
  skuId: string;
  manufacturerBatchNumber: string;
  expiryDate: string;
  receivedQuantity: number;
  acceptedQuantity: number;
  quarantinedQuantity: number;
  qualityStatus: BatchQualityStatus;
  temperatureExcursion: boolean;
}

export type LedgerEntryType =
  | "RECEIPT"
  | "ISSUE"
  | "TRANSFER_OUT"
  | "TRANSFER_IN"
  | "RETURN_OUT"
  | "RETURN_IN"
  | "ADJUSTMENT_INCREASE"
  | "ADJUSTMENT_DECREASE"
  | "STOCKTAKE_GAIN"
  | "STOCKTAKE_LOSS"
  | "EXPIRY"
  | "WRITE_OFF"
  | "DESTRUCTION"
  | "RESERVATION"
  | "RESERVATION_RELEASE";

export interface InventoryLedgerEntryDTO {
  id: string;
  branch: string;
  location: string;
  sku: string;
  inventoryBatch?: string;
  entryType: LedgerEntryType;
  quantityDelta: number;
  unit: string;
  baseQuantityDelta: number;
  transactionTimestamp: string;
  effectiveTimestamp: string;
}

export interface InventoryBalanceDTO {
  id: string;
  branch: string;
  location: string;
  sku: string;
  inventoryBatch?: string;
  qualityStatus: string;
  onHand: number;
  reserved: number;
  available: number;
  quarantined: number;
  damaged: number;
  expired: number;
  lastCalculatedAt: string;
}

export interface InventoryReservationDTO {
  id: string;
  branch: string;
  sourceLocation: string;
  sku: string;
  inventoryBatch?: string;
  requestedQuantity: number;
  allocatedQuantity: number;
  purpose: string;
  status: string;
  expiresAt?: string;
}
