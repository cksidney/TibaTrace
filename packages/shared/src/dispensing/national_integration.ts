/**
 * Shared TypeScript types for TibaTrace National Health & Regulatory Integration.
 *
 * Truth Labels — until live integration is verified, all status fields MUST use
 * one of the following truth labels:
 *   ADAPTER_SCAFFOLDED_NOT_CONNECTED
 *   NOT_CONFIGURED
 *   MANUAL_INTERNAL_VERIFICATION
 *   SNAPSHOT_IMPORTED_STALENESS_GOVERNED
 *   LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED
 *   MANUAL_VERIFICATION
 *   DISABLED_IN_PRODUCTION
 *   SANDBOX_EVIDENCE_ONLY
 *
 * STRICTLY FORBIDDEN (unless supported by executable evidence):
 *   CONNECTED, VERIFIED_BY_DHA, VERIFIED_BY_PPB, NATIONALLY_INTEGRATED, PRODUCTION_READY
 */

// ---------------------------------------------------------------------------
// Truth label type
// ---------------------------------------------------------------------------

export type IntegrationTruthLabel =
  | 'ADAPTER_SCAFFOLDED_NOT_CONNECTED'
  | 'NOT_CONFIGURED'
  | 'MANUAL_INTERNAL_VERIFICATION'
  | 'SNAPSHOT_IMPORTED_STALENESS_GOVERNED'
  | 'LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED'
  | 'MANUAL_VERIFICATION'
  | 'DISABLED_IN_PRODUCTION'
  | 'SANDBOX_EVIDENCE_ONLY'
  | 'PPB_API_ACTIVE'; // Only set when activation confirmed by Platform Owner.

// ---------------------------------------------------------------------------
// Phase 1 — Premises Verification Governance
// ---------------------------------------------------------------------------

export type PremisesVerificationState =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'UNDER_REVIEW'
  | 'CLARIFICATION_REQUIRED'
  | 'VERIFIED'
  | 'REJECTED'
  | 'SUSPENDED'
  | 'REVOKED'
  | 'SUPERSEDED';

export interface PremisesVerificationRequest {
  readonly id: string;
  readonly tenantId: string;
  readonly state: PremisesVerificationState;
  readonly submittedBy: string | null;
  readonly submittedAt: string | null;
  readonly reviewedBy: string | null;
  readonly reviewedAt: string | null;
  readonly reviewerNotes: string;
  readonly truthLabel: IntegrationTruthLabel;
  readonly createdAt: string;
}

export interface PremisesComplianceCheckResult {
  readonly isAllowed: boolean;
  readonly reasonCode: string;
  readonly truthLabel: IntegrationTruthLabel;
  readonly operation: string;
}

// ---------------------------------------------------------------------------
// Phase 2 — National Provider Integration Platform
// ---------------------------------------------------------------------------

export type ProviderType =
  | 'DHA_HIE'
  | 'DHA_HWR'
  | 'PPB_PREMISES'
  | 'PPB_PRODUCT_REGISTER'
  | 'PPB_REGULATORY_ALERTS'
  | 'PPB_RECALLS';

export type ProviderEnvironment = 'SANDBOX' | 'PRODUCTION';

export type ProviderActivationState =
  | 'REQUESTED'
  | 'UNDER_REVIEW'
  | 'SANDBOX_CONFIGURED'
  | 'SANDBOX_TESTING'
  | 'SANDBOX_PASSED'
  | 'SECURITY_APPROVED'
  | 'PRODUCTION_APPROVED'
  | 'ACTIVE'
  | 'SUSPENDED'
  | 'DECOMMISSIONED'
  | 'REJECTED';

export interface ProviderConfiguration {
  readonly id: string;
  readonly providerType: ProviderType;
  readonly environment: ProviderEnvironment;
  readonly displayName: string;
  readonly activationState: ProviderActivationState;
  readonly truthLabel: IntegrationTruthLabel;
  readonly isOperational: boolean;
  readonly activatedAt: string | null;
  readonly notes: string;
}

export interface ProviderHealthSnapshot {
  readonly providerId: string;
  readonly checkedAt: string;
  readonly isReachable: boolean;
  readonly responseTimeMs: number | null;
  readonly statusCode: number | null;
  readonly errorDetail: string;
  readonly truthLabel: IntegrationTruthLabel;
}

export interface IntegrationDeadLetterSummary {
  readonly id: string;
  readonly messageType: string;
  readonly providerId: string;
  readonly deadLetteredAt: string;
  readonly deadLetterReason: string;
  readonly replayedAt: string | null;
}

// ---------------------------------------------------------------------------
// Phase 4 — DHA HWR Practitioner Verification
// ---------------------------------------------------------------------------

export type HwrVerificationState =
  | 'UNVERIFIED'
  | 'PENDING'
  | 'VERIFIED'
  | 'STALE'
  | 'EXPIRED'
  | 'SUSPENDED'
  | 'REVOKED'
  | 'NOT_FOUND'
  | 'AMBIGUOUS'
  | 'PROVIDER_UNAVAILABLE'
  | 'VERIFICATION_FAILED';

export type HwrRegulator = 'KMPDC' | 'COC' | 'NCK' | 'PPB';

export interface HwrVerificationDecision {
  readonly state: HwrVerificationState;
  readonly canPrescribeRoutine: boolean;
  readonly canPrescribeControlled: boolean;
  readonly reasonCodes: readonly string[];
  readonly degradedMode: boolean;
  readonly truthLabel: IntegrationTruthLabel;
}

// ---------------------------------------------------------------------------
// Phase 5 & 6 — PPB Regulatory Product Status
// ---------------------------------------------------------------------------

export type RegulatoryProductStatus =
  | 'CURRENTLY_VERIFIED'
  | 'STALE'
  | 'SUSPENDED'
  | 'WITHDRAWN'
  | 'EXPIRED'
  | 'UNKNOWN'
  | 'MATCH_REQUIRES_REVIEW'
  | 'NOT_FOUND'
  | 'MANUAL_REVIEW_REQUIRED'
  | 'MANUAL_VERIFICATION';

export interface RegulatoryProductStatusResult {
  readonly registrationNumber: string;
  readonly productName: string;
  readonly status: RegulatoryProductStatus;
  readonly truthLabel: IntegrationTruthLabel;
}

// ---------------------------------------------------------------------------
// Phase 7 — Regulatory Alerts & Recalls
// ---------------------------------------------------------------------------

export type AlertSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';

export type AlertStatus =
  | 'DRAFT'
  | 'ACTIVE'
  | 'UNDER_REVIEW'
  | 'RESOLVED'
  | 'WITHDRAWN'
  | 'SUPERSEDED';

export type MatchConfidenceTier =
  | 'GTIN_EXACT'
  | 'PPB_REGISTRATION_EXACT'
  | 'PRODUCT_MANUFACTURER_MATCH'
  | 'BATCH_NUMBER_MATCH'
  | 'MANUAL_REVIEW';

export type TenantImpactState =
  | 'PENDING'
  | 'QUARANTINED'
  | 'UNDER_REVIEW'
  | 'RESOLVED'
  | 'RELEASED'
  | 'NOT_AFFECTED';

export interface RegulatoryAlert {
  readonly id: string;
  readonly alertReference: string;
  readonly title: string;
  readonly severity: AlertSeverity;
  readonly status: AlertStatus;
  readonly issuingRegulator: string;
  readonly regulatorIssueDate: string | null;
  readonly ppbRegistrationNumber: string;
  readonly gtin: string;
  readonly productName: string;
  readonly manufacturerName: string;
  readonly affectedBatches: readonly string[];
  readonly description: string;
  readonly recommendedAction: string;
  readonly truthLabel: IntegrationTruthLabel;
  readonly ingestedAt: string;
}

export interface RegulatoryTenantImpact {
  readonly id: string;
  readonly alertId: string;
  readonly tenantId: string;
  readonly state: TenantImpactState;
  readonly quarantinedAt: string | null;
  readonly affectedBatches: readonly string[];
  readonly quarantinedStockCount: number;
  readonly priorDispenseTraceRequired: boolean;
  readonly priorDispensePatientCount: number;
}

// ---------------------------------------------------------------------------
// HQ Integration Command Centre — display types
// ---------------------------------------------------------------------------

export interface IntegrationProviderCardData {
  readonly providerType: ProviderType;
  readonly displayName: string;
  readonly activationState: ProviderActivationState;
  readonly truthLabel: IntegrationTruthLabel;
  readonly lastHealthChecked: string | null;
  readonly isReachable: boolean | null;
  readonly pendingDeadLetters: number;
}
