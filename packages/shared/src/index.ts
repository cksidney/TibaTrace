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

export type CustomerType =
  | "INDIVIDUAL"
  | "PHARMACY"
  | "HOSPITAL"
  | "CLINIC"
  | "WHOLESALER"
  | "DISTRIBUTOR"
  | "GOVERNMENT"
  | "NGO"
  | "INSURER"
  | "CORPORATE"
  | "INTERNAL";

export type CustomerStatus =
  | "PROSPECTIVE"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "ACTIVE"
  | "SUSPENDED"
  | "BLOCKED"
  | "ARCHIVED";

export interface CustomerDTO {
  id: string;
  customerNumber: string;
  legalName: string;
  tradingName?: string;
  customerType: CustomerType;
  registrationNumber?: string;
  taxNumber?: string;
  contactEmail?: string;
  contactPhone?: string;
  status: CustomerStatus;
  riskClassification: string;
  creditStatus: string;
  defaultCurrency: string;
  paymentTerms: string;
  controlledMedicineEligible: boolean;
  coldChainCapable: boolean;
}

export interface CustomerDeliveryAddressDTO {
  id: string;
  customerId: string;
  addressCode: string;
  recipientName: string;
  addressLine1: string;
  city: string;
  county?: string;
  country: string;
  phone?: string;
  routeZone?: string;
  coldChainCapable: boolean;
  controlledMedicineCapable: boolean;
  isActive: boolean;
}

export type QuotationStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "APPROVED"
  | "SENT"
  | "ACCEPTED"
  | "CONVERTED"
  | "REJECTED"
  | "EXPIRED"
  | "CANCELLED";

export interface QuotationDTO {
  id: string;
  quotationNumber: string;
  branchId: string;
  customerId: string;
  deliveryAddressId?: string;
  currency: string;
  status: QuotationStatus;
  issueDate: string;
  validUntil?: string;
  subtotal: number;
  taxTotal: number;
  total: number;
  revision: number;
}

export type SalesOrderStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "RESERVED"
  | "PARTIALLY_ALLOCATED"
  | "ALLOCATED"
  | "PARTIALLY_PICKED"
  | "PICKED"
  | "PARTIALLY_PACKED"
  | "PACKED"
  | "PARTIALLY_DISPATCHED"
  | "DISPATCHED"
  | "PARTIALLY_DELIVERED"
  | "DELIVERED"
  | "CLOSED"
  | "REJECTED"
  | "ON_HOLD"
  | "BACKORDERED"
  | "CANCELLED";

export interface SalesOrderDTO {
  id: string;
  orderNumber: string;
  branchId: string;
  sourceQuotationId?: string;
  customerId: string;
  deliveryAddressId?: string;
  customerPoReference?: string;
  currency: string;
  orderDate: string;
  requestedDeliveryDate?: string;
  priority: number;
  fulfilmentPolicy: string;
  substitutionPolicy: string;
  invoicePolicy: string;
  subtotal: number;
  taxTotal: number;
  total: number;
  status: SalesOrderStatus;
}

export interface SalesOrderLineDTO {
  id: string;
  salesOrderId: string;
  skuId: string;
  descriptionSnapshot: string;
  requestedQuantity: number;
  approvedQuantity: number;
  reservedQuantity: number;
  allocatedQuantity: number;
  pickedQuantity: number;
  packedQuantity: number;
  dispatchedQuantity: number;
  deliveredQuantity: number;
  returnedQuantity: number;
  unit: string;
  agreedUnitPrice: number;
  discountAmount: number;
  taxAmount: number;
  lineTotal: number;
  status: string;
}

export interface PickingTaskDTO {
  id: string;
  pickingWaveId?: string;
  salesOrderId: string;
  salesOrderLineId: string;
  sourceLocationId: string;
  skuId: string;
  batchId?: string;
  requestedQuantity: number;
  pickedQuantity: number;
  shortQuantity: number;
  status: string;
  assignedPickerId?: string;
}

export interface PackageDTO {
  id: string;
  packingSessionId: string;
  packageNumber: string;
  salesOrderId: string;
  temperatureZone: string;
  packageType: string;
  sealNumber?: string;
  status: string;
}

export interface DispatchOrderDTO {
  id: string;
  dispatchNumber: string;
  branchId: string;
  warehouseId?: string;
  customerId: string;
  deliveryAddressId?: string;
  carrier?: string;
  status: string;
}

export interface DeliveryRecordDTO {
  id: string;
  dispatchOrderId: string;
  customerId: string;
  status: string;
  deliveredAt?: string;
  recipientName?: string;
  proofType?: string;
}

export interface SalesReturnAuthorizationDTO {
  id: string;
  returnNumber: string;
  salesOrderId: string;
  customerId: string;
  status: string;
  reason?: string;
}

export type DecimalString = string;

export type PrescriptionLifecycleStatus =
  | "RECEIVED"
  | "INTAKE_REVIEW"
  | "LEGALLY_VALIDATED"
  | "CLINICAL_REVIEW"
  | "PHARMACIST_VERIFIED"
  | "READY_FOR_DISPENSING"
  | "PARTIALLY_DISPENSED"
  | "DISPENSED"
  | "PARTIALLY_SUPPLIED"
  | "SUPPLIED"
  | "CLOSED"
  | "ON_HOLD"
  | "INTERVENTION_REQUIRED"
  | "REJECTED"
  | "CANCELLED"
  | "EXPIRED"
  | "RETURNED";

export type LegalValidationState =
  | "PENDING"
  | "PASSED"
  | "FAILED"
  | "MANUAL_REVIEW";

export type ClinicalReviewState =
  | "NOT_STARTED"
  | "IN_PROGRESS"
  | "FINDINGS_OPEN"
  | "COMPLETED"
  | "BLOCKED";

export type PharmacistVerificationState =
  | "NOT_VERIFIED"
  | "VERIFIED"
  | "REVOKED";

export type DispensingEpisodeStatus =
  | "DRAFT"
  | "PREPARING"
  | "CHECKING"
  | "READY_FOR_SUPPLY"
  | "PARTIALLY_SUPPLIED"
  | "SUPPLIED"
  | "CLOSED"
  | "ON_HOLD"
  | "CANCELLED"
  | "REVERSED"
  | "RETURNED";

export type ClinicalFindingSeverity =
  | "INFORMATION"
  | "LOW"
  | "MODERATE"
  | "HIGH"
  | "CRITICAL"
  | "INFO"
  | "WARNING"
  | "BLOCK";

export type ClinicalFindingResolution =
  | "OPEN"
  | "ACKNOWLEDGED"
  | "OVERRIDDEN"
  | "INTERVENTION_REQUIRED"
  | "RESOLVED"
  | "NOT_APPLICABLE";

export interface PatientIdentifierDTO {
  id: string;
  identifierType: string;
  system: string;
  maskedValue: string;
  verificationStatus: string;
  issuingAuthority?: string;
  issueDate?: string;
  expiryDate?: string;
}

export interface PatientDTO {
  id: string;
  internalReferenceId: string;
  patientNumber: string;
  externalPatientReference?: string;
  verificationStatus: string;
  firstName: string;
  lastName: string;
  preferredName?: string;
  dateOfBirth?: string;
  sex: string;
  preferredLanguage?: string;
  communicationPreference?: string;
  isDeceased: boolean;
  consentStatus: string;
  isActive: boolean;
  identifiers: PatientIdentifierDTO[];
}

export interface AllergyDTO {
  id: string;
  patientId: string;
  allergenName: string;
  allergenCode?: string;
  medicinalProductId?: string;
  activeIngredientId?: string;
  reaction?: string;
  severity: string;
  onsetDate?: string;
  verificationStatus: string;
  source: string;
  status: string;
  notes?: string;
  isActive: boolean;
}

export interface PatientClinicalSummaryDTO {
  id: string;
  patientId: string;
  pregnancyStatus: string;
  lactationStatus: string;
  renalImpairment: string;
  hepaticImpairment: string;
  heightCm?: DecimalString;
  weightKg?: DecimalString;
  source: string;
  verificationStatus: string;
  verifiedById?: string;
  verifiedAt?: string;
  updatedAt: string;
}

export interface PrescriberDTO {
  id: string;
  professionalName: string;
  registrationNumber: string;
  profession: string;
  licensingBody: string;
  licenceStatus: string;
  licenceIssueDate?: string;
  licenceExpiryDate?: string;
  prescribingScope: string[];
  controlledMedicineAuthority: boolean;
  organizationId?: string;
  verificationState: string;
  status: string;
}

export interface PrescriptionItemDTO {
  id: string;
  prescriptionId: string;
  prescribedMedicinalProductId?: string;
  prescribedBrandId?: string;
  prescribedSkuId?: string;
  prescribedDescriptionSnapshot: string;
  activeIngredientSnapshot: Record<string, unknown>[];
  strengthSnapshot: string;
  dosageFormSnapshot: string;
  route?: string;
  dosageInstruction: string;
  doseAmount?: DecimalString;
  doseUnit?: string;
  frequencyPerDay?: DecimalString;
  durationDays?: number;
  quantity: DecimalString;
  unit: string;
  refillsAuthorized: number;
  repeatsRemaining: number;
  quantitySuppliedTotal: DecimalString;
  minimumRepeatIntervalDays: number;
  earliestRefillDate?: string;
  latestRefillDate?: string;
  substitutionPolicy: string;
  isControlled: boolean;
  status: string;
}

export interface PrescriptionDTO {
  id: string;
  prescriptionNumber: string;
  externalPrescriptionReference?: string;
  patientId: string;
  practitionerId: string;
  organizationId: string;
  locationId: string;
  prescribingOrganizationId?: string;
  prescriptionDate?: string;
  receivedAt?: string;
  prescriptionType: string;
  sourceChannel: string;
  originalDocumentId?: string;
  status: PrescriptionLifecycleStatus;
  expiresAt?: string;
  isControlledMedicine: boolean;
  repeatAuthorization: boolean;
  repeatsAllowed: number;
  repeatsRemaining: number;
  legalValidationState: LegalValidationState;
  clinicalReviewState: ClinicalReviewState;
  pharmacistVerificationState: PharmacistVerificationState;
  dispensingState: string;
  items: PrescriptionItemDTO[];
}

export interface ClinicalFindingDTO extends ClinicalSourceAttribution {
  id: string;
  patientId: string;
  prescriptionId: string;
  prescriptionItemId?: string;
  affectedMedicineId?: string;
  ruleType: string;
  clinicalCategory: string;
  severity: ClinicalFindingSeverity;
  explanation: string;
  evidenceSummary: string;
  recommendedAction: string;
  overridePolicy: string;
  resolutionStatus: ClinicalFindingResolution;
  resolvedById?: string;
  resolutionReason?: string;
  resolvedAt?: string;
  detectedAt: string;
}

export interface PharmacistReviewDTO {
  id: string;
  prescriptionId: string;
  reviewingPharmacistId: string;
  reviewStartedAt: string;
  reviewCompletedAt?: string;
  outcome?: string;
  notes?: string;
  verificationDecision?: string;
  contextHash: string;
  version: number;
}

export interface PharmacistInterventionDTO {
  id: string;
  prescriptionId: string;
  prescriptionItemId?: string;
  reviewId: string;
  clinicalFindingId?: string;
  interventionType: string;
  contactedParty?: string;
  contactMethod?: string;
  interventionRequest: string;
  response?: string;
  originalInstruction: Record<string, unknown>;
  changedInstruction: Record<string, unknown>;
  prescriberAuthorization: Record<string, unknown>;
  outcome?: string;
  status: string;
  actorId: string;
  resolvedAt?: string;
}

export interface PharmacistVerificationDTO {
  id: string;
  prescriptionId: string;
  reviewId: string;
  verifiedById: string;
  decision: string;
  contextHash: string;
  verificationChecks: Record<string, boolean>;
  clinicalJustification?: string;
  verifiedAt: string;
  revokedAt?: string;
  revokedReason?: string;
}

export interface ClinicalSubstitutionDTO {
  id: string;
  prescriptionId: string;
  prescriptionItemId: string;
  prescribedSkuId?: string;
  proposedSkuId: string;
  equivalenceBasis: string;
  priceImpact: DecimalString;
  stockReason?: string;
  prescriberApproved: boolean;
  patientConsented: boolean;
  pharmacistApproved: boolean;
  approvedById?: string;
  status: string;
  reason: string;
}

export interface DispensingLineDTO {
  id: string;
  episodeId: string;
  prescriptionItemId: string;
  prescribedSkuId: string;
  suppliedSkuId: string;
  inventoryBatchId: string;
  inventoryAllocationId: string;
  quantityAuthorized: DecimalString;
  quantityPrepared: DecimalString;
  quantitySupplied: DecimalString;
  unit: string;
  packageDefinitionId: string;
  batchNumberSnapshot: string;
  expiryDateSnapshot: string;
  dosageLabelInstructions: string;
  substitutionId?: string;
  status: string;
  preparedById: string;
  checkerId?: string;
}

export interface DispensingEpisodeDTO {
  id: string;
  dispensingNumber: string;
  prescriptionId: string;
  patientId: string;
  branchId: string;
  pharmacyLocationId: string;
  pharmacistId: string;
  status: DispensingEpisodeStatus;
  initiatedAt: string;
  completedAt?: string;
  supplyMethod: string;
  salesOrderId?: string;
  paymentGateState: string;
  counsellingStatus: string;
  lines: DispensingLineDTO[];
}

export interface PatientCounsellingDTO {
  id: string;
  episodeId: string;
  patientId: string;
  counsellingRequired: boolean;
  counsellingCompleted: boolean;
  topics: string[];
  warningsExplained?: string;
  administrationInstructions?: string;
  storageGuidance?: string;
  adherenceAdvice?: string;
  sideEffectGuidance?: string;
  missedDoseGuidance?: string;
  deviceDemonstration: boolean;
  patientQuestions?: string;
  language?: string;
  interpreter?: string;
  counselledById?: string;
  counselledAt?: string;
  refusalReason?: string;
}

export interface RepeatDispensingDTO {
  prescriptionItemId: string;
  repeatsAuthorized: number;
  repeatsRemaining: number;
  minimumIntervalDays: number;
  earliestRefillDate?: string;
  latestRefillDate?: string;
  cumulativeSuppliedQuantity: DecimalString;
}

export interface PatientMedicationHistoryDTO {
  id: string;
  patientId: string;
  prescriptionId: string;
  prescriptionItemId: string;
  dispensingEpisodeId: string;
  medicineSupplyLineId: string;
  medicineNameSnapshot: string;
  suppliedSkuId: string;
  activeIngredientSnapshot: Record<string, unknown>[];
  strengthSnapshot: string;
  dosageFormSnapshot: string;
  inventoryBatchId: string;
  quantity: DecimalString;
  instructions: string;
  suppliedAt: string;
  status: string;
  source: string;
  reversalReferenceId?: string;
}

export interface PatientReturnDTO {
  id: string;
  returnNumber: string;
  supplyId: string;
  patientId: string;
  reason: string;
  receivedById: string;
  inspectedById?: string;
  quarantineLocationId: string;
  qualityDecision: string;
  destructionPath?: string;
  refundEligibility: string;
  status: string;
}

export type ClinicalQueueType =
  | "PRESCRIPTION_INTAKE"
  | "LEGAL_VALIDATION"
  | "CLINICAL_REVIEW"
  | "CRITICAL_DUR_FINDING"
  | "PRESCRIBER_CLARIFICATION"
  | "PATIENT_CLARIFICATION"
  | "PHARMACIST_VERIFICATION"
  | "READY_FOR_DISPENSING"
  | "DISPENSING_PREPARATION"
  | "FINAL_CHECK"
  | "READY_FOR_COUNSELLING"
  | "READY_FOR_SUPPLY"
  | "PARTIAL_DISPENSING_FOLLOW_UP"
  | "REPEAT_DUE"
  | "EARLY_REPEAT_REVIEW"
  | "CONTROLLED_MEDICINE_REVIEW"
  | "PATIENT_RETURN_INSPECTION"
  | "REVERSAL_APPROVAL";

export interface ClinicalWorkItemDTO {
  id: string;
  queueType: ClinicalQueueType;
  prescriptionId: string;
  prescriptionNumber: string;
  dispensingEpisodeId?: string;
  dispensingNumber?: string;
  branchId: string;
  branchName: string;
  requiredCapability: string;
  status: "OPEN" | "IN_PROGRESS" | "CLOSED" | "CANCELLED";
  dueAt?: string;
  closedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface DispensingReversalDTO {
  id: string;
  reversalNumber: string;
  supplyId: string;
  originalSupplyLineId: string;
  quantity: DecimalString;
  reason: string;
  authorizedById: string;
  physicallyReturned: boolean;
  returnCondition?: string;
  inventoryEligibility: string;
  reversedAt: string;
}

export interface PrescriptionVerificationAction {
  decision?: "VERIFIED" | "VERIFIED_WITH_COUNSELLING";
  clinicalJustification?: string;
  idempotencyKey: string;
}

export interface DispensingReserveAction {
  prescriptionItemId: string;
  quantity: DecimalString;
  minimumShelfLifeDays?: number;
  substituteSkuId?: string;
  idempotencyKey: string;
}

export interface DispensingSupplyAction {
  lineQuantities?: Record<string, DecimalString>;
  partialReason?: string;
  nextEligibleDate?: string;
  idempotencyKey: string;
}

export interface DispensingReversalRequestAction {
  supplyLineId: string;
  reason: string;
}

export interface DispensingReversalAction
  extends DispensingReversalRequestAction {
  quantity?: DecimalString;
  physicallyReturned?: boolean;
  returnCondition?: string;
  inventoryEligibility?: string;
  idempotencyKey: string;
}

export interface PaginatedResponse<T> {
  count: number;
  next?: string;
  previous?: string;
  results: T[];
}

// ─── POS Clinical Safety Plugin ─────────────────────────────────────────────────
export * from "./clinical/index.js";
export * from "./dispensing/index.js";
export * from "./design-system/index.js";
export * from "./auth/index.js";
export * from "./operational/index.js";
export * from "./retail/index.js";
