import { action, autoColumns, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { ClinicalStatus } from '@dawatrace/shared/design-system/index.js';
import {
  canApproveActivationRequest,
  type PosActivationRequestDTO,
  type PosActivationState,
} from '@dawatrace/shared/dispensing/index.js';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { BlockingReason, StatusBadge } from './StatusBadge.js';

export function PosActivationConsole({
  apiFetch,
  userId,
  userRole,
  userCapabilities,
  isPlatformOwnerContext,
  tenantId,
  deviceId,
  fingerprint = '',
  appVersion = '',
  onEnrolled,
  passwordChangeRequired = false,
}: {
  readonly apiFetch: typeof fetch;
  readonly userId: string;
  readonly userRole: string;
  readonly userCapabilities: readonly string[];
  readonly isPlatformOwnerContext: boolean;
  readonly tenantId: string;
  readonly deviceId: string;
  readonly fingerprint?: string;
  readonly appVersion?: string;
  readonly onEnrolled?: () => Promise<void>;
  readonly passwordChangeRequired?: boolean;
}) {
  const [requests, setRequests] = useState<readonly PosActivationRequestDTO[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [activeTab, setActiveTab] = useState<'CONSOLE' | 'NEW_REQUEST'>('CONSOLE');
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);

  // Platform Owner Action Modals
  const [actionKind, setActionKind] = useState<'APPROVE' | 'REJECT' | 'REVOKE' | null>(null);
  const [rationale, setRationale] = useState('');

  // New Request Form State (Tenant Admin)
  const newTenantId = tenantId;
  const [newBranchId, setNewBranchId] = useState('');
  const [newRegister, setNewRegister] = useState('');
  const [deviceName, setDeviceName] = useState('');
  const [deviceType, setDeviceType] = useState<'DESKTOP_WINDOWS' | 'MOBILE_ANDROID'>('DESKTOP_WINDOWS');
  const [deviceFingerprint, setDeviceFingerprint] = useState(fingerprint);
  const [justification, setJustification] = useState('');
  const [challenge, setChallenge] = useState('');
  const [enrolCode, setEnrolCode] = useState('');

  const canApprove = isPlatformOwnerContext && userCapabilities.includes('platform.pos_activation.approve');

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const endpoint = isPlatformOwnerContext
        ? '/api/v1/platform/pos-activations/requests/'
        : '/api/v1/tenant/pos-activations/requests/';
      const response = await apiFetch(endpoint, { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`Activation service returned HTTP ${response.status}.`);
      const data = await response.json() as PosActivationRequestDTO[] | { results?: PosActivationRequestDTO[] };
      const items = Array.isArray(data) ? data : (data.results ?? []);
      setRequests(items);
      setError('');
    } catch {
      setRequests([]);
      setError('POS activation service is unavailable. No local or simulated activation data is being used.');
    } finally {
      setBusy(false);
    }
  }, [apiFetch, isPlatformOwnerContext]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectedRequest = useMemo(
    () => requests.find((r) => r.id === selectedRequestId) ?? requests[0] ?? null,
    [requests, selectedRequestId],
  );

  const handleApprove = async () => {
    if (!selectedRequest || !actionKind || rationale.trim().length < 10) return;
    setBusy(true);
    setError('');
    const check = canApproveActivationRequest({
      actorUserId: userId,
      actorRole: userRole,
      actorCapabilities: userCapabilities,
      requesterUserId: selectedRequest.requestingUserId,
      isPlatformOwnerContext,
    });
    if (!check.allowed) {
      setError(check.reason);
      setBusy(false);
      return;
    }
    try {
      const resp = await apiFetch(`/api/v1/platform/pos-activations/requests/${selectedRequest.id}/${actionKind.toLowerCase()}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ rationale: rationale.trim() }),
      });
      if (resp.ok) {
        const result = await resp.json() as { challengeCode?: string };
        setChallenge(result.challengeCode ?? '');
        setNotice(`Request ${selectedRequest.id}: ${actionKind} recorded by Platform Owner.`);
        setActionKind(null);
        setRationale('');
        void refresh();
      } else {
        setError(`Approval failed closed (HTTP ${resp.status}). No activation challenge was issued.`);
      }
    } catch {
      setError('Action failed.');
    } finally {
      setBusy(false);
    }
  };

  const handleCreateRequest = async () => {
    if (!newTenantId.trim() || !newBranchId.trim() || !newRegister.trim() || !deviceId || deviceFingerprint.trim().length < 16 || justification.trim().length < 10) {
      setError('Provide the branch UUID, existing register code, stable device fingerprint and at least 10 characters of justification.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const resp = await apiFetch('/api/v1/tenant/pos-activations/requests/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          tenant_id: newTenantId.trim(),
          branch_id: newBranchId.trim(),
          requested_register: newRegister.trim(),
          device_id: deviceId,
          app_version: appVersion,
          device_name: deviceName.trim() || 'POS Workstation',
          device_type: deviceType,
          device_fingerprint: deviceFingerprint.trim(),
          business_justification: justification.trim(),
        }),
      });
      if (resp.ok) {
        setNotice('POS Activation request submitted to Platform Owner for review.');
        setActiveTab('CONSOLE');
        void refresh();
      } else {
        setError(`Activation request was not accepted (HTTP ${resp.status}). Nothing was queued locally.`);
      }
    } catch {
      setError('Failed to submit activation request.');
    } finally {
      setBusy(false);
    }
  };

  const handleEnrol = async () => {
    if (!selectedRequest || !enrolCode.trim()) return;
    setBusy(true);
    setError('');
    try {
      const response = await apiFetch(`/api/v1/tenant/pos-activations/requests/${selectedRequest.id}/enrol/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ challenge_code: enrolCode.trim(), device_id: deviceId, device_fingerprint: fingerprint }),
      });
      if (!response.ok) throw new Error(`Enrolment was not accepted (HTTP ${response.status}).`);
      setEnrolCode('');
      setNotice('Device enrolled. Secure credential storage and online activation validation are required before trading.');
      await onEnrolled?.();
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Enrolment could not be completed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.lg, padding: spacing.xl }}>
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: fontSize.screenTitle, color: text.primary }}>
            POS Device Activation Governance
          </h2>
          <p style={{ margin: `${spacing.xs}px 0 0`, fontSize: fontSize.body, color: text.secondary }}>
            {isPlatformOwnerContext
              ? 'Platform Owner Console — Authoritative Activation Review & Governance'
              : 'Tenant Activation Workspace — Submit and Track Device Activation Requests'}
          </p>
        </div>
        <StatusBadge
          status={isPlatformOwnerContext ? 'SAFE' : 'INFORMATION'}
          label={isPlatformOwnerContext ? 'PLATFORM OWNER CONTEXT' : 'TENANT REQUESTOR CONTEXT'}
        />
      </header>

      {notice ? (
        <div style={{ padding: spacing.md, borderRadius: 8, background: statusPalette.SAFE.surface, color: statusPalette.SAFE.foreground, fontWeight: 600 }}>
          {notice}
        </div>
      ) : null}

      {error ? <BlockingReason status="BLOCKING" reason={error} /> : null}
      {passwordChangeRequired ? <BlockingReason status="BLOCKING" reason="Change your temporary password in the HQ website at https://tibatrace.esenai.co.ke, then sign out and sign in again on this till." /> : null}
      {challenge ? <section role="status" style={{ padding: spacing.md, border: `1px solid ${surface.border}`, borderRadius: 8 }}>
        <strong>One-time enrolment challenge (expires in 15 minutes)</strong>
        <p>Give this code directly to the requesting Manager. It is shown only once and is not an activation credential.</p>
        <code style={{ overflowWrap: 'anywhere' }}>{challenge}</code>
        <button type="button" onClick={() => setChallenge('')}>Hide code</button>
      </section> : null}

      {/* Workspace Tabs */}
      <div style={{ display: 'flex', gap: spacing.sm, borderBottom: `1px solid ${surface.border}` }}>
        <button
          type="button"
          onClick={() => setActiveTab('CONSOLE')}
          style={{
            padding: '10px 16px',
            border: 'none',
            borderBottom: activeTab === 'CONSOLE' ? `3px solid ${action.primary}` : 'none',
            background: 'transparent',
            color: activeTab === 'CONSOLE' ? action.primary : text.secondary,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Activation Requests ({requests.length})
        </button>
        {!isPlatformOwnerContext ? (
          <button
            type="button"
            onClick={() => setActiveTab('NEW_REQUEST')}
            style={{
              padding: '10px 16px',
              border: 'none',
              borderBottom: activeTab === 'NEW_REQUEST' ? `3px solid ${action.primary}` : 'none',
              background: 'transparent',
              color: activeTab === 'NEW_REQUEST' ? action.primary : text.secondary,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            + Submit Activation Request
          </button>
        ) : null}
      </div>

      {activeTab === 'NEW_REQUEST' ? (
        <section style={{ display: 'flex', flexDirection: 'column', gap: spacing.md, maxWidth: 640, background: surface.raised, padding: spacing.xl, borderRadius: 12, border: `1px solid ${surface.border}` }}>
          <h3 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>New POS Activation Request</h3>
          <p style={{ margin: 0, fontSize: fontSize.caption, color: text.secondary }}>
            Tenant Administrators submit activation requests. Only the TibaTrace Platform Owner may review and approve POS device activations.
          </p>

          <label style={labelStyle}>
            Tenant ID
            <input value={newTenantId} readOnly style={inputStyle} />
          </label>
          <label style={labelStyle}>
            Branch ID
            <input value={newBranchId} onChange={(e) => setNewBranchId(e.target.value)} placeholder="Branch UUID from your HQ workspace" style={inputStyle} />
          </label>
          <label style={labelStyle}>
            Device ID
            <input value={deviceId} readOnly style={inputStyle} />
          </label>
          <label style={labelStyle}>
            Requested Register
            <input value={newRegister} onChange={(e) => setNewRegister(e.target.value)} placeholder="e.g. REG-01-DISPENSARY" style={inputStyle} />
          </label>
          <label style={labelStyle}>
            Device Name
            <input value={deviceName} onChange={(e) => setDeviceName(e.target.value)} placeholder="e.g. POS Workstation Dispensary 1" style={inputStyle} />
          </label>
          <label style={labelStyle}>
            Device Type
            <select value={deviceType} onChange={(e) => setDeviceType(e.target.value as any)} style={inputStyle}>
              <option value="DESKTOP_WINDOWS">Windows POS (Electron Desktop)</option>
              <option value="MOBILE_ANDROID">Android POS (React Native Mobile)</option>
            </select>
          </label>
          <label style={labelStyle}>
            Stable Installation Fingerprint (not hardware attestation)
            <input value={deviceFingerprint} readOnly={Boolean(fingerprint)} onChange={(e) => setDeviceFingerprint(e.target.value)} placeholder="Stable installation fingerprint" style={inputStyle} />
          </label>
          <label style={labelStyle}>
            Business Justification
            <textarea value={justification} onChange={(e) => setJustification(e.target.value)} rows={3} placeholder="Explain why this POS device activation is required..." style={{ ...inputStyle, minHeight: 80 }} />
          </label>

          <button type="button" disabled={busy || passwordChangeRequired} onClick={() => void handleCreateRequest()} style={buttonPrimary}>
            {busy ? 'Submitting…' : 'Submit Activation Request'}
          </button>
        </section>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: spacing.lg }}>
          {/* Request List Sidebar */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
            <h3 style={{ margin: 0, fontSize: fontSize.caption, textTransform: 'uppercase', color: text.tertiary, letterSpacing: 0.6 }}>
              Requests Queue
            </h3>
            {requests.map((r) => {
              const stateMeta = stateStatusMeta(r.state);
              const selected = selectedRequest?.id === r.id;
              return (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setSelectedRequestId(r.id)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                    padding: spacing.md,
                    borderRadius: 10,
                    border: `1px solid ${selected ? action.selectedBorder : surface.border}`,
                    background: selected ? action.selectedSurface : surface.raised,
                    textAlign: 'left',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, fontSize: fontSize.body }}>{r.id}</span>
                    <StatusBadge status={stateMeta.status} label={r.state} size="sm" />
                  </div>
                  <span style={{ fontSize: fontSize.caption, color: text.secondary }}>
                    {r.deviceName} · {r.branchId}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Request Detail & Governance Actions */}
          {selectedRequest ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.lg, background: surface.raised, padding: spacing.xl, borderRadius: 12, border: `1px solid ${surface.border}` }}>
              <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: fontSize.sectionTitle }}>{selectedRequest.deviceName}</h3>
                  <span style={{ fontSize: fontSize.caption, color: text.secondary }}>
                    {selectedRequest.id} · {selectedRequest.tenantId} · {selectedRequest.branchId}
                  </span>
                </div>
                <StatusBadge status={stateStatusMeta(selectedRequest.state).status} label={selectedRequest.state} />
              </header>

              <dl style={{ display: 'grid', gridTemplateColumns: autoColumns(160), gap: spacing.md, margin: 0 }}>
                <Detail label="Register" value={selectedRequest.requestedRegister} />
                <Detail label="Device Type" value={selectedRequest.deviceType} />
                <Detail label="OS / App" value={`${selectedRequest.osName} (${selectedRequest.appVersion})`} />
                <Detail label="Requester" value={`${selectedRequest.requesterEmailSnapshot} (${selectedRequest.requesterRole})`} />
                <Detail label="Correlation ID" value={selectedRequest.correlationId} />
                <Detail label="Fingerprint" value={selectedRequest.deviceFingerprint} />
              </dl>

              <div style={{ padding: spacing.md, borderRadius: 8, background: surface.sunken }}>
                <strong style={{ fontSize: fontSize.caption, color: text.tertiary, textTransform: 'uppercase' }}>Business Justification</strong>
                <p style={{ margin: `${spacing.xs}px 0 0`, fontSize: fontSize.body }}>{selectedRequest.businessJustification}</p>
              </div>

              {/* Platform Owner Governance Actions */}
              {!isPlatformOwnerContext && selectedRequest.state === 'APPROVED' && selectedRequest.deviceId === deviceId ? <section>
                <label style={labelStyle}>One-time enrolment challenge
                  <input value={enrolCode} onChange={(event) => setEnrolCode(event.target.value)} autoComplete="off" style={inputStyle} />
                </label>
                <button type="button" disabled={busy || passwordChangeRequired || !enrolCode.trim()} onClick={() => void handleEnrol()} style={buttonPrimary}>Complete device enrolment</button>
              </section> : null}
              {canApprove ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.md, borderTop: `1px solid ${surface.border}`, paddingTop: spacing.md }}>
                  <h4 style={{ margin: 0, fontSize: fontSize.caption, textTransform: 'uppercase', color: text.tertiary }}>
                    Platform Owner Approval Governance
                  </h4>
                  <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap' }}>
                    <button type="button" disabled={busy || selectedRequest.state !== 'SUBMITTED'} onClick={() => setActionKind('APPROVE')} style={buttonPrimary}>
                      Approve & Issue Challenge
                    </button>
                    <button type="button" disabled={busy || selectedRequest.state !== 'SUBMITTED'} onClick={() => setActionKind('REJECT')} style={buttonSecondary}>
                      Reject Request
                    </button>
                    <button type="button" onClick={() => setActionKind('REVOKE')} style={buttonSecondary}>
                      Revoke Device
                    </button>
                  </div>

                  {actionKind ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm, marginTop: spacing.sm }}>
                      <label style={labelStyle}>
                        Approval / Governance Rationale (Required)
                        <input value={rationale} onChange={(e) => setRationale(e.target.value)} placeholder="Provide rationale for regulatory & audit log..." style={inputStyle} />
                      </label>
                      <button type="button" disabled={busy || rationale.trim().length < 10} onClick={() => void handleApprove()} style={buttonPrimary}>
                        {busy ? 'Processing…' : `Confirm ${actionKind}`}
                      </button>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div style={{ padding: spacing.md, borderRadius: 8, background: surface.sunken, fontSize: fontSize.caption, color: text.secondary }}>
                  🔒 Platform Owner approval required for activation state changes. Tenant Admins cannot approve or activate POS devices.
                </div>
              )}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt style={{ fontSize: fontSize.meta, color: text.tertiary, textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</dt>
      <dd style={{ margin: '2px 0 0', fontSize: fontSize.body, fontWeight: 600, color: text.primary }}>{value}</dd>
    </div>
  );
}

function stateStatusMeta(state: PosActivationState): { status: ClinicalStatus } {
  switch (state) {
    case 'ACTIVATED':
    case 'APPROVED':
      return { status: 'SAFE' };
    case 'SUBMITTED':
    case 'UNDER_REVIEW':
    case 'RENEWAL_REQUESTED':
      return { status: 'ACTION_REQUIRED' };
    case 'SUSPENDED':
    case 'CLARIFICATION_REQUIRED':
      return { status: 'INFORMATION' };
    case 'REJECTED':
    case 'REVOKED':
    case 'EXPIRED':
      return { status: 'BLOCKING' };
    default:
      return { status: 'DISABLED' };
  }
}

const labelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  fontSize: fontSize.caption,
  color: text.secondary,
};

const inputStyle: React.CSSProperties = {
  padding: '10px 12px',
  borderRadius: 8,
  border: `1px solid ${surface.borderStrong}`,
  fontSize: fontSize.body,
  backgroundColor: surface.raised,
  color: text.primary,
};

const buttonPrimary: React.CSSProperties = {
  padding: '10px 18px',
  borderRadius: 8,
  border: 'none',
  background: action.primary,
  color: action.primaryForeground,
  fontWeight: 700,
  fontSize: fontSize.body,
  cursor: 'pointer',
};

const buttonSecondary: React.CSSProperties = {
  padding: '10px 18px',
  borderRadius: 8,
  border: `1px solid ${surface.borderStrong}`,
  background: surface.raised,
  color: text.primary,
  fontWeight: 600,
  fontSize: fontSize.body,
  cursor: 'pointer',
};
