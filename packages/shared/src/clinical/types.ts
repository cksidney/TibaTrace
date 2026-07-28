/**
 * TibaTrace POS Drug Interaction & Clinical Safety Plugin
 * Shared Type Definitions
 *
 * These contracts are shared between Windows POS, Android POS, and the backend API.
 * All POS clients MUST use these types for clinical screening communication.
 */

// ─── Enumerations ───────────────────────────────────────────────────────────────

/** All supported clinical finding categories */
export type ClinicalFindingCategory =
  | "DRUG_DRUG_INTERACTION"
  | "DRUG_ALLERGY"
  | "DUPLICATE_THERAPY"
  | "CONTRAINDICATION"
  | "DOSE_TOO_HIGH"
  | "DOSE_TOO_LOW"
  | "FREQUENCY_TOO_HIGH"
  | "FREQUENCY_TOO_LOW"
  | "DURATION_TOO_LONG"
  | "DURATION_TOO_SHORT"
  | "AGE_RESTRICTION"
  | "WEIGHT_BASED_DOSE"
  | "RENAL_IMPAIRMENT"
  | "HEPATIC_IMPAIRMENT"
  | "PREGNANCY_WARNING"
  | "LACTATION_WARNING"
  | "CONTROLLED_MEDICINE_RULE"
  | "EARLY_REPEAT"
  | "THERAPEUTIC_DUPLICATION"
  | "MAXIMUM_DAILY_DOSE"
  | "FORMULARY_RESTRICTION"
  | "PRESCRIPTION_REQUIRED"
  | "PHARMACIST_VERIFICATION_REQUIRED"
  | "INSUFFICIENT_PATIENT_DATA"
  | "STALE_CLINICAL_DATA"
  | "OFFLINE_SCREENING_UNAVAILABLE";

/** CDS severity levels (aligns with Phase 5 ClinicalKnowledgeRule.severity) */
export type ClinicalSeverity =
  | "INFORMATION"
  | "LOW"
  | "MODERATE"
  | "HIGH"
  | "CRITICAL";

/** Plugin screening mode — controlled per-tenant */
export type ClinicalScreeningMode =
  | "DISABLED"
  | "ADVISORY"
  | "PHARMACIST_REVIEW_REQUIRED"
  | "STRICT";

/** Status of a screening evaluation */
export type ClinicalScreeningStatus =
  | "PENDING"
  | "COMPLETE"
  | "INCOMPLETE_DATA"
  | "OFFLINE_CACHE"
  | "FAILED"
  | "STALE"
  | "INVALIDATED";

/** Resolution status of an individual clinical finding */
export type ClinicalFindingResolution =
  | "OPEN"
  | "ACKNOWLEDGED"
  | "PHARMACIST_REVIEWED"
  | "OVERRIDDEN"
  | "RESOLVED";

/** Pharmacist decision outcomes */
export type PharmacistDecisionType =
  | "APPROVE"
  | "APPROVE_WITH_CONDITIONS"
  | "RETURN_FOR_CORRECTION"
  | "REJECT"
  | "CONTACT_PRESCRIBER"
  | "REQUIRE_ALTERNATIVE"
  | "REQUEST_MORE_INFORMATION"
  | "APPROVE_AS_WRITTEN"
  | "APPROVE_WITH_COUNSELLING"
  | "REMOVE_MEDICINE"
  | "CHANGE_QUANTITY"
  | "APPROVED_SUBSTITUTION"
  | "PRESCRIBER_CLARIFICATION_REQUIRED"
  | "PATIENT_CLARIFICATION_REQUIRED"
  | "HOLD_TRANSACTION"
  | "REJECT_SUPPLY"
  | "AUTHORIZED_OVERRIDE";

/** Override reason categories */
export type ClinicalOverrideReason =
  | "KNOWN_AND_MONITORED"
  | "CLINICALLY_JUSTIFIED"
  | "PRESCRIBER_CONFIRMED"
  | "PATIENT_ALREADY_STABLE"
  | "DOSE_ADJUSTED"
  | "DUPLICATION_INTENTIONAL"
  | "SHORT_DURATION"
  | "PALLIATIVE_CARE"
  | "SPECIALIST_INSTRUCTION"
  | "OTHER";

/** Offline clinical state */
export type OfflineClinicalState =
  | "ONLINE_VERIFIED"
  | "OFFLINE_CACHE_VALID"
  | "OFFLINE_LIMITED"
  | "OFFLINE_BLOCKED";

/** Basket line interaction indicator for UI */
export type BasketInteractionIndicator =
  | "INFO"
  | "CAUTION"
  | "PHARMACIST"
  | "BLOCKED";

/** Pharmacist authentication method */
export type PharmacistAuthMethod =
  | "LOGIN"
  | "PIN"
  | "BADGE"
  | "BIOMETRIC"
  | "SUPERVISOR";

/** Clinical content lifecycle status */
export type ClinicalContentStatus =
  | "DRAFT"
  | "CLINICAL_REVIEW"
  | "APPROVED"
  | "PUBLISHED"
  | "SUPERSEDED"
  | "RETIRED";

// ─── POS Transaction Context ───────────────────────────────────────────────────

/** A single basket line for clinical screening */
export interface PosClinicalBasketLine {
  lineId: string;
  commercialSkuId?: string;
  clinicalMedicinalProductId?: string;
  manufacturedMedicinalProductId?: string;
  activeIngredientIds?: string[];
  prescriptionItemId?: string;
  medicineName: string;
  strength?: string;
  dosageForm?: string;
  route?: string;
  quantity: number;
  doseInstructions?: string;
  doseValue?: number;
  doseUnit?: string;
  frequencyPerDay?: number;
  durationDays?: number;
  isControlled?: boolean;
  isPrescriptionOnly?: boolean;
  batchId?: string;
  batchNumber?: string;
  batchExpiryDate?: string;
  batchRecalled?: boolean;
}

/** Complete clinical context sent with screening request */
export interface PosClinicalContext {
  tenantId: string;
  branchId: string;
  deviceId: string;
  registerId?: string;
  transactionId: string;
  /**
   * Recorded as basket context, not as an authorisation claim. Every clinical
   * write authorises against the authenticated session instead.
   */
  cashierId: string;
  patientId?: string;
  patientName?: string;
  prescriptionId?: string;
  dispensingEpisodeId?: string;
  basketLines: PosClinicalBasketLine[];
  contextHash?: string;
  screeningTimestamp: string;
  offlineState: boolean;
}

/** Patient context — pharmacist-visible fields only */
export interface PosClinicalPatientContext {
  patientId: string;
  patientName: string;
  dateOfBirth?: string;
  ageYears?: number;
  weightKg?: number;
  pregnancyStatus?: string;
  lactationStatus?: string;
  renalImpairment?: boolean;
  hepaticImpairment?: boolean;
  allergies: PosPatientAllergy[];
  activeMedicines: PosActiveMedicine[];
  recentSupplyHistory: PosRecentSupply[];
}

export interface PosPatientAllergy {
  allergenCode: string;
  allergenName: string;
  severity: string;
  reactionType?: string;
}

export interface PosActiveMedicine {
  medicineId: string;
  medicineName: string;
  activeIngredientCodes: string[];
  startDate?: string;
  prescribedBy?: string;
}

export interface PosRecentSupply {
  medicineId: string;
  medicineName: string;
  suppliedAt: string;
  quantity: number;
  prescriptionRef?: string;
}

// ─── Screening Results ──────────────────────────────────────────────────────────

/** A single clinical finding from the screening */
export interface PosClinicalFinding {
  id: string;
  ruleId: string;
  ruleVersion: string;
  category: ClinicalFindingCategory;
  severity: ClinicalSeverity;
  title: string;
  summary: string;
  clinicalExplanation?: string;
  recommendation?: string;
  affectedBasketLineIds: string[];
  affectedMedicineIds: string[];
  patientContextRequired: boolean;
  blocking: boolean;
  requiresPharmacist: boolean;
  overrideAllowed: boolean;
  overrideCapability?: string;
  evidenceSource?: string;
  detectedAt: string;
  expiresAt?: string;
  resolutionStatus: ClinicalFindingResolution;
}

/** Complete screening result returned by the API */
export interface PosClinicalScreeningResult {
  screeningId: string;
  contextHash: string;
  patientId?: string;
  prescriptionId?: string;
  findings: PosClinicalFinding[];
  highestSeverity: ClinicalSeverity | null;
  blockingFindings: number;
  requiresPharmacistReview: boolean;
  safeToProceed: boolean;
  screeningStatus: ClinicalScreeningStatus;
  evaluatedAt: string;
  ruleSetVersion: string;
  decisions: PosClinicalDecisionHistory[];
}

/** Immutable pharmacist decision history returned with a screening. */
export interface PosClinicalDecisionHistory {
  id: string;
  findingId?: string;
  pharmacistId: string;
  pharmacistName: string;
  decision: PharmacistDecisionType;
  clinicalJustification: string;
  conditions?: string;
  counsellingNotes?: string;
  prescriberContactRef?: string;
  followUpActions?: string;
  contextHashAtDecision: string;
  ruleVersionAtDecision: string;
  branchId?: string;
  transactionId: string;
  registerId?: string;
  patientRef?: string;
  prescriptionRef?: string;
  createdAt: string;
}

// ─── API Request/Response Contracts ─────────────────────────────────────────────

/** Request body for POST /api/pos/clinical-screening/evaluate/ */
export interface PosClinicalScreeningRequest {
  transactionId: string;
  deviceId: string;
  registerId?: string;
  patientId?: string;
  prescriptionId?: string;
  dispensingEpisodeId?: string;
  basketLines: PosClinicalBasketLine[];
  contextHash?: string;
  clientScreenedAt?: string;
  offlineState?: boolean;
}

/** Request body for POST .../acknowledge/ */
export interface PosClinicalAcknowledgement {
  findingId: string;
  /** Required; the server refuses a write against a changed basket. */
  expectedContextHash: string;
}

/** Request body for POST .../request-pharmacist/ */
export interface PosPharmacistReviewRequest {
  /**
   * The context the caller believes it is acting on. Required: the server
   * refuses the write if the basket changed after screening, and omitting it
   * fails closed rather than skipping the check.
   */
  expectedContextHash: string;
  urgencyNote?: string;
}

/** Request body for POST .../pharmacist-review/ */
export interface PosPharmacistDecision {
  findingId?: string;
  /**
   * The deciding pharmacist is the authenticated user. It is deliberately not a
   * field here: the API previously resolved the actor from a client-supplied
   * id, which let a caller nominate whose authority to act under -- a cashier
   * could pass a pharmacist's id and approve their own override. Authority now
   * comes from the session alone.
   */
  expectedContextHash: string;
  authMethod: PharmacistAuthMethod;
  decision: PharmacistDecisionType;
  clinicalJustification?: string;
  conditions?: string;
  counsellingNotes?: string;
  prescriberContactRef?: string;
  followUpActions?: string;
  overrideReason?: ClinicalOverrideReason;
  idempotencyKey: string;
}

/** Request body for POST .../override/ */
export interface PosClinicalOverride {
  findingId: string;
  overrideReason: ClinicalOverrideReason;
  /** Mandatory. The server rejects an override without one. */
  clinicalJustification: string;
  overrideCapability: string;
  idempotencyKey: string;
  expectedContextHash: string;
}

/** Offline clinical sync record */
export interface PosClinicalSyncRecord {
  syncId: string;
  deviceId: string;
  screeningId: string;
  eventType: string;
  payload: Record<string, unknown>;
  createdAt: string;
  syncedAt?: string;
  syncStatus: "PENDING" | "SYNCED" | "CONFLICT" | "FAILED";
  retryCount: number;
}

// ─── Offline Package ────────────────────────────────────────────────────────────

/** Offline clinical rule package downloaded by POS clients */
export interface PosOfflineClinicalPackage {
  version: string;
  ruleSetVersion: string;
  tenantId: string;
  generatedAt: string;
  expiresAt: string;
  signature: string;
  rules: PosOfflineRule[];
  ingredientMappings: PosIngredientMapping[];
  controlledClassifications: PosControlledClassification[];
  allergenCrossSensitivities: PosAllergenCrossSensitivity[];
  duplicateTherapyGroups: PosDuplicateTherapyGroup[];
}

export interface PosOfflineRule {
  ruleId: string;
  ruleType: string;
  severity: ClinicalSeverity;
  primaryCode: string;
  interactingCode: string;
  title: string;
  summary: string;
  clinicalExplanation: string;
  recommendation: string;
  overridePolicy: string;
  criteria: Record<string, unknown>;
  effectiveFrom: string;
  effectiveTo?: string;
}

export interface PosIngredientMapping {
  skuId: string;
  clinicalProductId: string;
  ingredientCodes: string[];
}

export interface PosControlledClassification {
  skuId: string;
  schedule: string;
  prescriptionRequired: boolean;
}

export interface PosAllergenCrossSensitivity {
  allergenCode: string;
  crossSensitiveCodes: string[];
}

export interface PosDuplicateTherapyGroup {
  groupCode: string;
  groupName: string;
  ingredientCodes: string[];
}

// ─── Plugin Configuration ───────────────────────────────────────────────────────

/** Plugin activation and behaviour configuration */
export interface DrugInteractionPluginConfig {
  drugInteractionPluginEnabled: boolean;
  clinicalScreeningMode: ClinicalScreeningMode;
  patientSelectionRequired: boolean;
  prescriptionRequiredForRestrictedItems: boolean;
  blockCriticalInteractions: boolean;
  requirePharmacistForHighSeverity: boolean;
  allowOfflineDispensing: boolean;
  offlineClinicalCacheMaximumAgeHours: number;
  screenNonPrescriptionMedicines: boolean;
  screenRecentMedicationHistory: boolean;
  screenPatientAllergies: boolean;
  screenDuplicateTherapy: boolean;
  screenContraindications: boolean;
  screenDoseAndFrequency: boolean;
  screenControlledMedicines: boolean;
}

/** Default plugin configuration */
export const DEFAULT_DRUG_INTERACTION_CONFIG: DrugInteractionPluginConfig = {
  drugInteractionPluginEnabled: false,
  clinicalScreeningMode: "DISABLED",
  patientSelectionRequired: false,
  prescriptionRequiredForRestrictedItems: true,
  blockCriticalInteractions: true,
  requirePharmacistForHighSeverity: true,
  allowOfflineDispensing: false,
  offlineClinicalCacheMaximumAgeHours: 720,
  screenNonPrescriptionMedicines: true,
  screenRecentMedicationHistory: true,
  screenPatientAllergies: true,
  screenDuplicateTherapy: true,
  screenContraindications: true,
  screenDoseAndFrequency: true,
  screenControlledMedicines: true,
};

// ─── Transaction Safety Panel ───────────────────────────────────────────────────

/** Summary data for the POS transaction-level clinical safety panel */
export interface PosClinicalSafetyPanelState {
  screeningStatus: ClinicalScreeningStatus | "NOT_SCREENED";
  patientSelected: boolean;
  prescriptionVerified: boolean;
  totalFindings: number;
  blockingFindings: number;
  pharmacistReviewStatus: "NOT_REQUIRED" | "PENDING" | "COMPLETED";
  ruleSetVersion: string;
  offlineState: OfflineClinicalState;
  lastScreenedAt?: string;
}

// ─── API Error Types ────────────────────────────────────────────────────────────

/** Typed clinical screening API errors */
export type PosClinicalError =
  | "PATIENT_REQUIRED"
  | "PRESCRIPTION_REQUIRED"
  | "PHARMACIST_REQUIRED"
  | "CLINICAL_BLOCK"
  | "RULESET_STALE"
  | "OFFLINE_NOT_ALLOWED"
  | "INVALID_OVERRIDE"
  | "INSUFFICIENT_CLINICAL_DATA"
  | "SCREENING_CONTEXT_CHANGED"
  | "SCREENING_NOT_FOUND"
  | "FINDING_NOT_FOUND"
  | "UNAUTHORIZED"
  | "IDEMPOTENCY_CONFLICT";

/** Structured error response from the clinical screening API */
export interface PosClinicalErrorResponse {
  error: PosClinicalError;
  message: string;
  details?: Record<string, unknown>;
}

// ─── Performance Instrumentation ────────────────────────────────────────────────

/** Performance metrics collected by the plugin */
export interface PosClinicalPerformanceMetrics {
  basketChangeToScreeningRequestMs?: number;
  screeningApiDurationMs?: number;
  resultRenderDurationMs?: number;
  pharmacistReviewDurationMs?: number;
  offlineScreeningDurationMs?: number;
  screeningCacheHitRate?: number;
  screeningFailureRate?: number;
  clinicalBlockRate?: number;
  overrideRate?: number;
}

// ─── RBAC Capabilities ──────────────────────────────────────────────────────────

/** POS clinical screening capabilities */
export const POS_CLINICAL_CAPABILITIES = {
  VIEW_SCREENING: "pos.clinical_screening.view",
  VIEW_FINDINGS_SUMMARY: "pos.clinical_findings.view_summary",
  VIEW_FINDINGS_DETAIL: "pos.clinical_findings.view_detail",
  REQUEST_REVIEW: "pos.clinical_review.request",
  PERFORM_REVIEW: "pos.clinical_review.perform",
  ACKNOWLEDGE_FINDING: "pos.clinical_findings.acknowledge",
  OVERRIDE_LOW: "pos.clinical_findings.override_low",
  OVERRIDE_MODERATE: "pos.clinical_findings.override_moderate",
  OVERRIDE_HIGH: "pos.clinical_findings.override_high",
  OVERRIDE_CRITICAL: "pos.clinical_findings.override_critical",
  CONTROLLED_MEDICINE_REVIEW: "pos.controlled_medicine.review",
  OFFLINE_SUPPLY: "pos.clinical_offline_supply",
  VIEW_AUDIT: "pos.clinical_audit.view",
} as const;

/** Role-to-capability mapping */
export const POS_CLINICAL_ROLE_CAPABILITIES: Record<string, string[]> = {
  CASHIER: [
    POS_CLINICAL_CAPABILITIES.VIEW_SCREENING,
    POS_CLINICAL_CAPABILITIES.VIEW_FINDINGS_SUMMARY,
    POS_CLINICAL_CAPABILITIES.REQUEST_REVIEW,
    POS_CLINICAL_CAPABILITIES.ACKNOWLEDGE_FINDING,
  ],
  PHARMACY_ASSISTANT: [
    POS_CLINICAL_CAPABILITIES.VIEW_SCREENING,
    POS_CLINICAL_CAPABILITIES.VIEW_FINDINGS_SUMMARY,
    POS_CLINICAL_CAPABILITIES.VIEW_FINDINGS_DETAIL,
    POS_CLINICAL_CAPABILITIES.REQUEST_REVIEW,
    POS_CLINICAL_CAPABILITIES.ACKNOWLEDGE_FINDING,
  ],
  PHARMACIST: [
    POS_CLINICAL_CAPABILITIES.VIEW_SCREENING,
    POS_CLINICAL_CAPABILITIES.VIEW_FINDINGS_SUMMARY,
    POS_CLINICAL_CAPABILITIES.VIEW_FINDINGS_DETAIL,
    POS_CLINICAL_CAPABILITIES.REQUEST_REVIEW,
    POS_CLINICAL_CAPABILITIES.PERFORM_REVIEW,
    POS_CLINICAL_CAPABILITIES.ACKNOWLEDGE_FINDING,
    POS_CLINICAL_CAPABILITIES.OVERRIDE_LOW,
    POS_CLINICAL_CAPABILITIES.OVERRIDE_MODERATE,
    POS_CLINICAL_CAPABILITIES.OVERRIDE_HIGH,
    POS_CLINICAL_CAPABILITIES.CONTROLLED_MEDICINE_REVIEW,
    POS_CLINICAL_CAPABILITIES.OFFLINE_SUPPLY,
  ],
  CLINICAL_ADMIN: [
    POS_CLINICAL_CAPABILITIES.VIEW_SCREENING,
    POS_CLINICAL_CAPABILITIES.VIEW_FINDINGS_SUMMARY,
    POS_CLINICAL_CAPABILITIES.VIEW_FINDINGS_DETAIL,
    POS_CLINICAL_CAPABILITIES.VIEW_AUDIT,
  ],
  AUDITOR: [
    POS_CLINICAL_CAPABILITIES.VIEW_SCREENING,
    POS_CLINICAL_CAPABILITIES.VIEW_FINDINGS_SUMMARY,
    POS_CLINICAL_CAPABILITIES.VIEW_FINDINGS_DETAIL,
    POS_CLINICAL_CAPABILITIES.VIEW_AUDIT,
  ],
};

/** Request body for POST .../acknowledge/ */
export interface PosAcknowledgementRequest {
  findingId: string;
  expectedContextHash: string;
}
