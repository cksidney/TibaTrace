import { describe, expect, it } from 'vitest';
import {
  canApproveActivationRequest,
  canTransitionActivationState,
  evaluateActivationQuota,
  isPlatformOwnerCapability,
  validateOfflineLease,
  validatePosStartup,
} from './posActivation.js';
import type { PosDeviceCredentialDTO, PosOfflineLeaseDTO } from './posActivation.js';

describe('POS Activation Governance Module', () => {
  describe('Capability & Role Verification', () => {
    it('identifies platform owner capabilities correctly', () => {
      expect(isPlatformOwnerCapability('platform.pos_activation.approve')).toBe(true);
      expect(isPlatformOwnerCapability('platform.pos_activation.revoke')).toBe(true);
      expect(isPlatformOwnerCapability('tenant.pos_activation.request')).toBe(false);
    });

    it('denies approval to tenant-scoped contexts', () => {
      const result = canApproveActivationRequest({
        actorUserId: 'user-platform-1',
        actorRole: 'TENANT_ADMIN',
        actorCapabilities: ['platform.pos_activation.approve'],
        requesterUserId: 'user-tenant-2',
        isPlatformOwnerContext: false,
      });
      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('strictly prohibited');
    });

    it('denies approval when requester attempts self-approval (Segregation of Duties)', () => {
      const result = canApproveActivationRequest({
        actorUserId: 'user-platform-1',
        actorRole: 'PLATFORM_OWNER',
        actorCapabilities: ['platform.pos_activation.approve'],
        requesterUserId: 'user-platform-1',
        isPlatformOwnerContext: true,
      });
      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('Segregation of Duties');
    });

    it('allows approval for authorized Platform Owner on another user request', () => {
      const result = canApproveActivationRequest({
        actorUserId: 'user-platform-owner-1',
        actorRole: 'PLATFORM_OWNER',
        actorCapabilities: ['platform.pos_activation.approve'],
        requesterUserId: 'user-tenant-admin-2',
        isPlatformOwnerContext: true,
      });
      expect(result.allowed).toBe(true);
    });
  });

  describe('State Machine Transitions', () => {
    it('allows valid lifecycle transitions', () => {
      expect(canTransitionActivationState('DRAFT', 'SUBMITTED')).toBe(true);
      expect(canTransitionActivationState('SUBMITTED', 'UNDER_REVIEW')).toBe(true);
      expect(canTransitionActivationState('UNDER_REVIEW', 'APPROVED')).toBe(true);
      expect(canTransitionActivationState('APPROVED', 'ACTIVATED')).toBe(true);
      expect(canTransitionActivationState('ACTIVATED', 'SUSPENDED')).toBe(true);
      expect(canTransitionActivationState('SUSPENDED', 'ACTIVATED')).toBe(true);
      expect(canTransitionActivationState('ACTIVATED', 'REVOKED')).toBe(true);
    });

    it('rejects invalid or unauthorized direct state jumps', () => {
      expect(canTransitionActivationState('DRAFT', 'ACTIVATED')).toBe(false);
      expect(canTransitionActivationState('SUBMITTED', 'ACTIVATED')).toBe(false);
      expect(canTransitionActivationState('REVOKED', 'ACTIVATED')).toBe(false);
    });
  });

  describe('Quota & Limit Evaluation', () => {
    it('flags quota breaches when standard limit is exceeded', () => {
      const result = evaluateActivationQuota({
        tenantId: 'TENANT-01',
        branchId: 'BRANCH-01',
        standardLimit: 5,
        currentActiveCount: 5,
        requestedCount: 1,
      });
      expect(result.isExceeded).toBe(true);
      expect(result.isOverrideApproved).toBe(false);
    });

    it('permits quota breach when Platform Owner override is explicitly approved', () => {
      const result = evaluateActivationQuota({
        tenantId: 'TENANT-01',
        branchId: 'BRANCH-01',
        standardLimit: 5,
        currentActiveCount: 5,
        requestedCount: 1,
        isOverrideApproved: true,
        overrideReason: 'Approved expansion for promotional period',
        overrideApproverId: 'PLATFORM-OWNER-01',
      });
      expect(result.isExceeded).toBe(true);
      expect(result.isOverrideApproved).toBe(true);
    });
  });

  describe('POS Startup Activation Gate', () => {
    const validCredential: PosDeviceCredentialDTO = {
      activationId: 'ACT-9901',
      tenantId: 'TENANT-01',
      branchId: 'BRANCH-01',
      deviceId: 'DEV-WIN-01',
      deviceFingerprint: 'FP-SHA256-ABCDEF123456',
      appVersion: '1.0.1',
      minimumRequiredBuild: '1.0.0',
      state: 'ACTIVATED',
      issuedAt: '2026-08-01T10:00:00Z',
      expiresAt: '2027-08-01T10:00:00Z',
      signedToken: 'TOKEN.SIGNED.XYZ',
      isRevoked: false,
    };

    it('passes for valid active credential', () => {
      const res = validatePosStartup({
        credential: validCredential,
        currentFingerprint: 'FP-SHA256-ABCDEF123456',
        currentTenantId: 'TENANT-01',
        currentBranchId: 'BRANCH-01',
        currentAppVersion: '1.0.1',
        currentSystemTimeIso: '2026-08-01T12:00:00Z',
      });
      expect(res.valid).toBe(true);
      expect(res.status).toBe('SAFE');
    });

    it('fails closed when credential is missing', () => {
      const res = validatePosStartup({
        credential: null,
        currentFingerprint: 'FP-SHA256-ABCDEF123456',
        currentTenantId: 'TENANT-01',
        currentBranchId: 'BRANCH-01',
        currentAppVersion: '1.0.1',
        currentSystemTimeIso: '2026-08-01T12:00:00Z',
      });
      expect(res.valid).toBe(false);
      expect(res.status).toBe('BLOCKING');
      expect(res.reason).toContain('Platform Owner');
    });

    it('fails closed when credential is revoked', () => {
      const res = validatePosStartup({
        credential: { ...validCredential, isRevoked: true, state: 'REVOKED' },
        currentFingerprint: 'FP-SHA256-ABCDEF123456',
        currentTenantId: 'TENANT-01',
        currentBranchId: 'BRANCH-01',
        currentAppVersion: '1.0.1',
        currentSystemTimeIso: '2026-08-01T12:00:00Z',
      });
      expect(res.valid).toBe(false);
      expect(res.reason).toContain('REVOKED');
    });

    it('fails closed on fingerprint mismatch', () => {
      const res = validatePosStartup({
        credential: validCredential,
        currentFingerprint: 'FP-TAMPERED-WRONG',
        currentTenantId: 'TENANT-01',
        currentBranchId: 'BRANCH-01',
        currentAppVersion: '1.0.1',
        currentSystemTimeIso: '2026-08-01T12:00:00Z',
      });
      expect(res.valid).toBe(false);
      expect(res.reason).toContain('fingerprint mismatch');
    });

    it('fails closed on expired credential', () => {
      const res = validatePosStartup({
        credential: { ...validCredential, expiresAt: '2026-07-01T00:00:00Z' },
        currentFingerprint: 'FP-SHA256-ABCDEF123456',
        currentTenantId: 'TENANT-01',
        currentBranchId: 'BRANCH-01',
        currentAppVersion: '1.0.1',
        currentSystemTimeIso: '2026-08-01T12:00:00Z',
      });
      expect(res.valid).toBe(false);
      expect(res.reason).toContain('EXPIRED');
    });
  });

  describe('Offline Activation Lease', () => {
    const validLease: PosOfflineLeaseDTO = {
      leaseId: 'LEASE-001',
      activationId: 'ACT-9901',
      tenantId: 'TENANT-01',
      branchId: 'BRANCH-01',
      deviceId: 'DEV-WIN-01',
      issuedAt: '2026-08-01T00:00:00Z',
      expiresAt: '2026-08-02T00:00:00Z',
      maxOfflineHours: 24,
      lastOnlineRevalidationAt: '2026-08-01T00:00:00Z',
      signature: 'SIG-OFFLINE-ABC',
      isRevoked: false,
    };

    it('validates active offline lease', () => {
      const res = validateOfflineLease({
        lease: validLease,
        currentTenantId: 'TENANT-01',
        currentBranchId: 'BRANCH-01',
        currentDeviceId: 'DEV-WIN-01',
        currentSystemTimeIso: '2026-08-01T12:00:00Z',
      });
      expect(res.valid).toBe(true);
    });

    it('rejects expired offline lease', () => {
      const res = validateOfflineLease({
        lease: validLease,
        currentTenantId: 'TENANT-01',
        currentBranchId: 'BRANCH-01',
        currentDeviceId: 'DEV-WIN-01',
        currentSystemTimeIso: '2026-08-03T12:00:00Z',
      });
      expect(res.valid).toBe(false);
      expect(res.reason).toContain('expired');
    });
  });
});
