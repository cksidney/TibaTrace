import type { ClinicalStatus } from '../design-system/clinicalStatus.js';

/**
 * States for POS Activation Lifecycle.
 * Enforces strict backend-governed state machine. Direct PATCH of status is prohibited.
 */
export type PosActivationState =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'UNDER_REVIEW'
  | 'CLARIFICATION_REQUIRED'
  | 'APPROVED'
  | 'REJECTED'
  | 'ACTIVATED'
  | 'SUSPENDED'
  | 'REVOKED'
  | 'EXPIRED'
  | 'TRANSFER_REQUESTED'
  | 'RENEWAL_REQUESTED'
  | 'CANCELLED';

/** Platform Owner capabilities (strictly platform-scoped). */
export type PlatformActivationCapability =
  | 'platform.pos_activation.review'
  | 'platform.pos_activation.approve'
  | 'platform.pos_activation.activate'
  | 'platform.pos_activation.suspend'
  | 'platform.pos_activation.revoke'
  | 'platform.pos_activation.transfer'
  | 'platform.pos_activation.renew'
  | 'platform.pos_activation.override_limit';

/** Tenant capabilities (requesting, viewing, responding only). */
export type TenantActivationCapability =
  | 'tenant.pos_activation.request'
  | 'tenant.pos_activation.view'
  | 'tenant.pos_activation.withdraw'
  | 'tenant.pos_activation.respond'
  | 'tenant.pos_activation.request_renewal'
  | 'tenant.pos_activation.request_transfer';

export type PosActivationCapability = PlatformActivationCapability | TenantActivationCapability;

export const PLATFORM_ACTIVATION_CAPABILITIES: readonly PlatformActivationCapability[] = [
  'platform.pos_activation.review',
  'platform.pos_activation.approve',
  'platform.pos_activation.activate',
  'platform.pos_activation.suspend',
  'platform.pos_activation.revoke',
  'platform.pos_activation.transfer',
  'platform.pos_activation.renew',
  'platform.pos_activation.override_limit',
];

export const TENANT_ACTIVATION_CAPABILITIES: readonly TenantActivationCapability[] = [
  'tenant.pos_activation.request',
  'tenant.pos_activation.view',
  'tenant.pos_activation.withdraw',
  'tenant.pos_activation.respond',
  'tenant.pos_activation.request_renewal',
  'tenant.pos_activation.request_transfer',
];

/** Check if a capability belongs to the Platform Owner authority. */
export function isPlatformOwnerCapability(capability: string): boolean {
  return (PLATFORM_ACTIVATION_CAPABILITIES as readonly string[]).includes(capability);
}

/** Check valid state transitions. Direct PATCH prohibited. */
export function canTransitionActivationState(
  from: PosActivationState,
  to: PosActivationState,
): boolean {
  if (from === to) return true;
  switch (from) {
    case 'DRAFT':
      return to === 'SUBMITTED' || to === 'CANCELLED';
    case 'SUBMITTED':
      return to === 'UNDER_REVIEW' || to === 'CANCELLED';
    case 'UNDER_REVIEW':
      return to === 'CLARIFICATION_REQUIRED' || to === 'APPROVED' || to === 'REJECTED';
    case 'CLARIFICATION_REQUIRED':
      return to === 'UNDER_REVIEW' || to === 'SUBMITTED' || to === 'CANCELLED';
    case 'APPROVED':
      return to === 'ACTIVATED' || to === 'SUSPENDED' || to === 'REVOKED' || to === 'CANCELLED';
    case 'ACTIVATED':
      return (
        to === 'SUSPENDED' ||
        to === 'REVOKED' ||
        to === 'EXPIRED' ||
        to === 'TRANSFER_REQUESTED' ||
        to === 'RENEWAL_REQUESTED'
      );
    case 'SUSPENDED':
      return to === 'ACTIVATED' || to === 'REVOKED';
    case 'TRANSFER_REQUESTED':
      return to === 'APPROVED' || to === 'ACTIVATED' || to === 'REVOKED' || to === 'CANCELLED';
    case 'RENEWAL_REQUESTED':
      return to === 'APPROVED' || to === 'ACTIVATED' || to === 'EXPIRED' || to === 'CANCELLED';
    case 'REVOKED':
      return to === 'DRAFT';
    case 'REJECTED':
    case 'CANCELLED':
    case 'EXPIRED':
      return to === 'DRAFT';
    default:
      return false;
  }
}

/** Full metadata structure for a POS Activation Request. */
export interface PosActivationRequestDTO {
  readonly id: string;
  readonly tenantId: string;
  readonly branchId: string;
  readonly requestedRegister: string;
  readonly deviceId: string;
  readonly deviceFingerprint: string;
  readonly deviceName: string;
  readonly deviceType: 'DESKTOP_WINDOWS' | 'MOBILE_ANDROID' | 'TABLET' | 'WORKSTATION';
  readonly osName: string;
  readonly osVersion: string;
  readonly appVersion: string;
  readonly hardwareSerialNumber?: string;
  readonly tpmIdentity?: string;
  readonly networkContextIp?: string;
  readonly requestingUserId: string;
  readonly requesterEmailSnapshot: string;
  readonly requesterRole: string;
  readonly businessJustification: string;
  readonly requestedPeriodDays: number;
  readonly requestedCapabilities: readonly string[];
  readonly replacementDeviceRef?: string;
  readonly previousActivationRef?: string;
  readonly supportingAttachments: readonly string[];
  readonly state: PosActivationState;
  readonly submittedAt?: string;
  readonly reviewedAt?: string;
  readonly reviewerId?: string;
  readonly approvalRationale?: string;
  readonly rejectionRationale?: string;
  readonly activationExpiry?: string;
  readonly correlationId: string;
}

/** One-time enrolment challenge for approved requests. */
export interface PosEnrolmentChallenge {
  readonly challengeCode: string;
  readonly requestId: string;
  readonly tenantId: string;
  readonly branchId: string;
  readonly deviceId: string;
  readonly deviceFingerprint: string;
  readonly expiresAt: string;
  readonly isUsed: boolean;
}

/** Device-bound activation credential issued upon successful enrolment. */
export interface PosDeviceCredentialDTO {
  readonly activationId: string;
  readonly tenantId: string;
  readonly branchId: string;
  readonly deviceId: string;
  readonly deviceFingerprint: string;
  readonly appVersion: string;
  readonly minimumRequiredBuild: string;
  readonly state: PosActivationState;
  readonly issuedAt: string;
  readonly expiresAt: string;
  readonly signedToken: string;
  readonly isRevoked: boolean;
}

/** Signed offline activation lease for governed offline operation. */
export interface PosOfflineLeaseDTO {
  readonly leaseId: string;
  readonly activationId: string;
  readonly tenantId: string;
  readonly branchId: string;
  readonly deviceId: string;
  readonly issuedAt: string;
  readonly expiresAt: string;
  readonly maxOfflineHours: number;
  readonly lastOnlineRevalidationAt: string;
  readonly signature: string;
  readonly isRevoked: boolean;
}

/** Quota Evaluation Result. */
export interface PosQuotaEvaluation {
  readonly tenantId: string;
  readonly branchId: string;
  readonly standardLimit: number;
  readonly currentActiveCount: number;
  readonly requestedCount: number;
  readonly isExceeded: boolean;
  readonly isOverrideApproved: boolean;
  readonly overrideReason?: string | undefined;
  readonly overrideApproverId?: string | undefined;
}

/**
 * Validates whether an actor can approve a POS activation.
 * Enforces strict Segregation of Duties:
 * 1. Actor MUST possess `platform.pos_activation.approve`
 * 2. Requester CANNOT approve their own request
 * 3. Tenant context CANNOT approve (must be Platform Owner context)
 */
export function canApproveActivationRequest(params: {
  readonly actorUserId: string;
  readonly actorRole: string;
  readonly actorCapabilities: readonly string[];
  readonly requesterUserId: string;
  readonly isPlatformOwnerContext: boolean;
}): { readonly allowed: boolean; readonly reason: string } {
  if (!params.isPlatformOwnerContext) {
    return {
      allowed: false,
      reason: 'Tenant administrators and tenant-scoped roles are strictly prohibited from approving POS activations.',
    };
  }
  if (params.actorUserId === params.requesterUserId) {
    return {
      allowed: false,
      reason: 'Segregation of Duties breach: Requesters cannot approve their own activation request.',
    };
  }
  if (!params.actorCapabilities.includes('platform.pos_activation.approve')) {
    return {
      allowed: false,
      reason: 'Actor lacks mandatory capability platform.pos_activation.approve.',
    };
  }
  return { allowed: true, reason: 'Approved by authorized Platform Owner.' };
}

/** Evaluates quota limits for a tenant branch. */
export function evaluateActivationQuota(input: {
  readonly tenantId: string;
  readonly branchId: string;
  readonly standardLimit: number;
  readonly currentActiveCount: number;
  readonly requestedCount: number;
  readonly isOverrideApproved?: boolean;
  readonly overrideReason?: string;
  readonly overrideApproverId?: string;
}): PosQuotaEvaluation {
  const isExceeded = input.currentActiveCount + input.requestedCount > input.standardLimit;
  return {
    tenantId: input.tenantId,
    branchId: input.branchId,
    standardLimit: input.standardLimit,
    currentActiveCount: input.currentActiveCount,
    requestedCount: input.requestedCount,
    isExceeded,
    isOverrideApproved: !!input.isOverrideApproved && !!input.overrideReason,
    overrideReason: input.overrideReason,
    overrideApproverId: input.overrideApproverId,
  };
}

/**
 * Validates POS Startup Activation Gate.
 * Fails closed if activation does not exist, is not ACTIVATED, is expired, revoked,
 * or fails device fingerprint/branch/tenant checks.
 */
export function validatePosStartup(input: {
  readonly credential: PosDeviceCredentialDTO | null;
  readonly currentFingerprint: string;
  readonly currentTenantId: string;
  readonly currentBranchId: string;
  readonly currentAppVersion: string;
  readonly currentSystemTimeIso: string;
}): { readonly valid: boolean; readonly status: ClinicalStatus; readonly reason: string } {
  if (!input.credential) {
    return {
      valid: false,
      status: 'BLOCKING',
      reason: 'POS Activation missing. Device must be activated by Platform Owner before launch.',
    };
  }
  if (input.credential.isRevoked || input.credential.state === 'REVOKED') {
    return {
      valid: false,
      status: 'BLOCKING',
      reason: 'POS Activation has been REVOKED by Platform Owner.',
    };
  }
  if (input.credential.state === 'SUSPENDED') {
    return {
      valid: false,
      status: 'BLOCKING',
      reason: 'POS Activation is SUSPENDED pending review.',
    };
  }
  if (input.credential.state !== 'ACTIVATED') {
    return {
      valid: false,
      status: 'BLOCKING',
      reason: `POS Activation is in invalid state (${input.credential.state}). Active status required.`,
    };
  }
  if (input.credential.tenantId !== input.currentTenantId) {
    return {
      valid: false,
      status: 'BLOCKING',
      reason: 'Cross-tenant activation mismatch detected. Access denied.',
    };
  }
  if (input.credential.branchId !== input.currentBranchId) {
    return {
      valid: false,
      status: 'BLOCKING',
      reason: 'Branch activation mismatch detected. Terminal belongs to another branch.',
    };
  }
  if (input.credential.deviceFingerprint !== input.currentFingerprint) {
    return {
      valid: false,
      status: 'BLOCKING',
      reason: 'Hardware device fingerprint mismatch detected. Activation bound to another device.',
    };
  }

  const currentTime = new Date(input.currentSystemTimeIso).getTime();
  const expiryTime = new Date(input.credential.expiresAt).getTime();
  if (Number.isNaN(currentTime) || Number.isNaN(expiryTime) || currentTime >= expiryTime) {
    return {
      valid: false,
      status: 'BLOCKING',
      reason: 'POS Activation credential has EXPIRED. Platform Owner renewal required.',
    };
  }

  return {
    valid: true,
    status: 'SAFE',
    reason: 'Device activation verified and safe for operational dispensing.',
  };
}

/** Validates Offline Activation Lease. */
export function validateOfflineLease(input: {
  readonly lease: PosOfflineLeaseDTO | null;
  readonly currentTenantId: string;
  readonly currentBranchId: string;
  readonly currentDeviceId: string;
  readonly currentSystemTimeIso: string;
}): { readonly valid: boolean; readonly reason: string } {
  if (!input.lease) {
    return { valid: false, reason: 'No offline activation lease found.' };
  }
  if (input.lease.isRevoked) {
    return { valid: false, reason: 'Offline activation lease has been revoked.' };
  }
  if (
    input.lease.tenantId !== input.currentTenantId ||
    input.lease.branchId !== input.currentBranchId ||
    input.lease.deviceId !== input.currentDeviceId
  ) {
    return { valid: false, reason: 'Offline lease context mismatch.' };
  }
  const currentTime = new Date(input.currentSystemTimeIso).getTime();
  const leaseExpiry = new Date(input.lease.expiresAt).getTime();
  if (Number.isNaN(currentTime) || Number.isNaN(leaseExpiry) || currentTime >= leaseExpiry) {
    return { valid: false, reason: 'Offline activation lease has expired. Re-connect online.' };
  }
  return { valid: true, reason: 'Offline activation lease valid.' };
}
