import { action, fontSize, spacing, surface, text } from '@dawatrace/shared/design-system/index.js';
import {
  validatePosStartup,
  type PosDeviceCredentialDTO,
} from '@dawatrace/shared/dispensing/index.js';
import { useState } from 'react';

import { BlockingReason, StatusBadge } from './StatusBadge.js';

export function PosActivationStartupGate({
  credential,
  currentFingerprint,
  currentTenantId,
  currentBranchId,
  currentAppVersion,
  onEnrolChallenge,
  onEnrolSuccess,
  children,
}: {
  readonly credential: PosDeviceCredentialDTO | null;
  readonly currentFingerprint: string;
  readonly currentTenantId: string;
  readonly currentBranchId: string;
  readonly currentAppVersion: string;
  readonly onEnrolChallenge?: (challengeCode: string) => Promise<PosDeviceCredentialDTO>;
  readonly onEnrolSuccess?: (credential: PosDeviceCredentialDTO) => void;
  readonly children: React.ReactNode;
}) {
  const [challengeInput, setChallengeInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [enrolError, setEnrolError] = useState('');

  const startupCheck = validatePosStartup({
    credential,
    currentFingerprint,
    currentTenantId,
    currentBranchId,
    currentAppVersion,
    currentSystemTimeIso: new Date().toISOString(),
  });

  if (startupCheck.valid) {
    return <>{children}</>;
  }

  const handleEnrol = async () => {
    if (!challengeInput.trim()) return;
    setBusy(true);
    setEnrolError('');
    if (!onEnrolChallenge) {
      setEnrolError('The authoritative enrolment service is unavailable. Activation remains blocked.');
      setBusy(false);
      return;
    }
    try {
      const issuedCredential = await onEnrolChallenge(challengeInput.trim());
      const issuedCheck = validatePosStartup({
        credential: issuedCredential,
        currentFingerprint,
        currentTenantId,
        currentBranchId,
        currentAppVersion,
        currentSystemTimeIso: new Date().toISOString(),
      });
      if (!issuedCheck.valid) {
        setEnrolError(`The enrolment service returned an unusable credential: ${issuedCheck.reason}`);
        return;
      }
      onEnrolSuccess?.(issuedCredential);
    } catch {
      setEnrolError('Enrolment failed closed. The challenge was not accepted by the activation service.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', backgroundColor: surface.page, padding: spacing.xl }}>
      <div style={{ width: '100%', maxWidth: 480, display: 'flex', flexDirection: 'column', gap: spacing.lg, background: surface.raised, padding: spacing.xxl ?? spacing.xl, borderRadius: 16, border: `1px solid ${surface.border}`, boxShadow: '0 8px 32px rgba(0,0,0,0.08)' }}>
        <header style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: spacing.sm }}>
          <StatusBadge status={startupCheck.status} label="POS ACTIVATION GATE" />
          <h2 style={{ margin: `${spacing.xs}px 0 0`, fontSize: fontSize.screenTitle, color: text.primary }}>
            POS Terminal Not Activated
          </h2>
          <p style={{ margin: 0, fontSize: fontSize.body, color: text.secondary }}>
            This terminal must be approved and activated by the TibaTrace Platform Owner before operational dispensing is permitted.
          </p>
        </header>

        <BlockingReason status="BLOCKING" reason={startupCheck.reason} />

        {enrolError ? <BlockingReason status="BLOCKING" reason={enrolError} /> : null}

        <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm, borderTop: `1px solid ${surface.border}`, paddingTop: spacing.md }}>
          <label style={{ fontSize: fontSize.caption, color: text.secondary, textTransform: 'uppercase', letterSpacing: 0.6 }}>
            Enter Enrolment Challenge Code
          </label>
          <input
            value={challengeInput}
            onChange={(e) => setChallengeInput(e.target.value)}
            placeholder="ENROL-CODE-XXXXXX"
            style={{
              padding: '12px 14px',
              borderRadius: 8,
              border: `1px solid ${surface.borderStrong}`,
              fontSize: 18,
              fontWeight: 700,
              letterSpacing: 1,
              backgroundColor: surface.raised,
              color: text.primary,
            }}
          />
          <button
            type="button"
            disabled={busy || !challengeInput.trim()}
            onClick={() => void handleEnrol()}
            style={{
              padding: '12px 20px',
              borderRadius: 8,
              border: 'none',
              background: action.primary,
              color: action.primaryForeground,
              fontWeight: 700,
              fontSize: fontSize.bodyLarge,
              cursor: busy || !challengeInput.trim() ? 'not-allowed' : 'pointer',
              marginTop: spacing.xs,
            }}
          >
            {busy ? 'Verifying Enrolment…' : 'Complete Device Enrolment'}
          </button>
        </div>

        <div style={{ fontSize: fontSize.meta, color: text.tertiary, textAlign: 'center', lineHeight: 1.5 }}>
          Tenant ID: <code>{currentTenantId}</code> · Branch: <code>{currentBranchId}</code><br />
          Fingerprint: <code>{currentFingerprint.slice(0, 16)}…</code>
        </div>
      </div>
    </div>
  );
}
