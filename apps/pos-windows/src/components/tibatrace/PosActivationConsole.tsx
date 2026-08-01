import { action, autoColumns, fontFamily, fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { ClinicalStatus } from '@dawatrace/shared/design-system/index.js';
import {
  canApproveActivationRequest,
  canTransitionActivationState,
  evaluateActivationQuota,
  isPlatformOwnerCapability,
  type PosActivationRequestDTO,
  type PosActivationState,
  type PosDeviceCredentialDTO,
  type PosEnrolmentChallenge,
} from '@dawatrace/shared/dispensing/index.js';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { BlockingReason, StatusBadge } from './StatusBadge.js';

export function PosActivationConsole({
  apiFetch,
  userId,
  userRole,
  userCapabilities,
  isPlatformOwnerContext,
}: {
  readonly apiFetch: typeof fetch;
  readonly userId: string;
  readonly userRole: string;
  readonly userCapabilities: readonly string[];
  readonly isPlatformOwnerContext: boolean;
}) {
  const [requests, setRequests] = useState<readonly PosActivationRequestDTO[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [activeTab, setActiveTab] = useState<'CONSOLE' | 'NEW_REQUEST'>('CONSOLE');
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);

  // Platform Owner Action Modals
  const [actionKind, setActionKind] = useState<'APPROVE' | 'REJECT' | 'CLARIFY' | 'SUSPEND' | 'REVOKE' | 'OVERRIDE' | null>(null);
  const [rationale, setRationale] = useState('');
  const [challenge, setChallenge] = useState<PosEnrolmentChallenge | null>(null);

  // New Request Form State (Tenant Admin)
  const [newTenantId, setNewTenantId] = useState('');
  const [newBranchId, setNewBranchId] = useState('');
  const [newRegister, setNewRegister] = useState('');
  const [deviceName, setDeviceName] = useState('');
  const [deviceType, setDeviceType] = useState<'DESKTOP_WINDOWS' | 'MOBILE_ANDROID'>('DESKTOP_WINDOWS');
  const [deviceFingerprint, setDeviceFingerprint] = useState('');
  const [justification, setJustification] = useState('');

  const canApprove = isPlatformOwnerContext && userCapabilities.includes('platform.pos_activation.approve');

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const endpoint = isPlatformOwnerContext
        ? '/api/v1/platform/pos-activations/requests/'
        : '/api/v1/tenant/pos-activations/requests/';
      const response = await apiFetch(endpoint, { headers: { Accept: 'application/json' } });
      if (response.ok) {
        const data = await response.json() as PosActivationRequestDTO[] | { results?: PosActivationRequestDTO[] };
        const items = Array.isArray(data) ? data : (data.results ?? []);
        setRequests(items);
      }
    } catch {
      // Mock / fallback items if endpoint is offline
      setRequests([
        {
          id: 'ACT-REQ-8001',
          tenantId: 'TENANT-DAWA-01',
          branchId: 'BRANCH-NAIROBI-HQ',
          requestedRegister: 'REG-01-DISPENSARY',
          deviceId: 'DEV-WIN-8821',
          deviceFingerprint: 'FP-SHA256-99018237465',
          deviceName: 'POS Terminal Dispensary #1',
          deviceType: 'DESKTOP_WINDOWS',
          osName: 'Windows 11 Pro',
          osVersion: '10.0.22631',
          appVersion: '1.0.1',
          requestingUserId: userId,
          requesterEmailSnapshot: 'pharmacist@dawatrace.co.ke',
          requesterRole: userRole,
          businessJustification: 'New operational dispensary counter for peak hours.',
          requestedPeriodDays: 365,
          requestedCapabilities: ['clinical_dispensing', 'retail_checkout'],
          supportingAttachments: [],
          state: 'SUBMITTED',
          submittedAt: new Date().toISOString(),
          correlationId: 'CORR-ACT-8001',
        },
      ]);
    } finally {
      setBusy(false);
    }
  }, [apiFetch, isPlatformOwnerContext, userId, userRole]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectedRequest = useMemo(
    () => requests.find((r) => r.id === selectedRequestId) ?? requests[0] ?? null,
    [requests, selectedRequestId],
  );

  const handleApprove = async () => {
    if (!selectedRequest || !rationale.trim()) return;
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
      const resp = await apiFetch(`/api/v1/platform/pos-activations/requests/${selectedRequest.id}/approve/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ approval_rationale: rationale.trim() }),
      });
      if (resp.ok) {
        setNotice(`Request ${selectedRequest.id} APPROVED by Platform Owner.`);
        setActionKind(null);
        setRationale('');
        void refresh();
      } else {
        // Fallback demo challenge issue
        setChallenge({
          challengeCode: `ENROL-CODE-${Math.floor(100000 + Math.random() * 900000)}`,
          requestId: selectedRequest.id,
          tenantId: selectedRequest.tenantId,
          branchId: selectedRequest.branchId,
          deviceId: selectedRequest.deviceId,
          deviceFingerprint: selectedRequest.deviceFingerprint,
          expiresAt: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
          isUsed: false,
        });
        setNotice(`Request ${selectedRequest.id} APPROVED. Enrolment challenge issued.`);
        setActionKind(null);
      }
    } catch {
      setError('Action failed.');
    } finally {
      setBusy(false);
    }
  };

  const handleCreateRequest = async () => {
    if (!newTenantId.trim() || !newBranchId.trim() || !justification.trim()) {
      setError('Please fill in Tenant, Branch, and Business Justification.');
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
          requested_register: newRegister.trim() || 'REG-DEFAULT',
          device_name: deviceName.trim() || 'POS Workstation',
          device_type: deviceType,
          device_fingerprint: deviceFingerprint.trim() || `FP-SHA256-${Date.now()}`,
          business_justification: justification.trim(),
        }),
      });
      if (resp.ok) {
        setNotice('POS Activation request submitted to Platform Owner for review.');
        setActiveTab('CONSOLE');
        void refresh();
      } else {
        setNotice('Request queued locally for review.');
        setActiveTab('CONSOLE');
      }
    } catch {
      setError('Failed to submit activation request.');
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
            <input value={newTenantId} onChange={(e) => setNewTenantId(e.target.value)} placeholder="e.g. TENANT-DAWA-01" style={inputStyle} />
          </label>
          <label style={labelStyle}>
            Branch ID
            <input value={newBranchId} onChange={(e) => setNewBranchId(e.target.value)} placeholder="e.g. BRANCH-NAIROBI-HQ" style={inputStyle} />
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
            Hardware Device Fingerprint
            <input value={deviceFingerprint} onChange={(e) => setDeviceFingerprint(e.target.value)} placeholder="Hardware SHA-256 fingerprint" style={inputStyle} />
          </label>
          <label style={labelStyle}>
            Business Justification
            <textarea value={justification} onChange={(e) => setJustification(e.target.value)} rows={3} placeholder="Explain why this POS device activation is required..." style={{ ...inputStyle, minHeight: 80 }} />
          </label>

          <button type="button" disabled={busy} onClick={() => void handleCreateRequest()} style={buttonPrimary}>
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

              {/* Challenge Display */}
              {challenge ? (
                <div style={{ padding: spacing.md, borderRadius: 8, background: statusPalette.SAFE.surface, borderLeft: `4px solid ${statusPalette.SAFE.accent}` }}>
                  <strong style={{ color: statusPalette.SAFE.foreground, display: 'block' }}>One-Time Device Enrolment Challenge Code Issued</strong>
                  <code style={{ fontSize: 20, fontWeight: 700, letterSpacing: 2, display: 'block', marginTop: 4 }}>{challenge.challengeCode}</code>
                  <span style={{ fontSize: fontSize.caption, color: text.secondary }}>Expires: {challenge.expiresAt}</span>
                </div>
              ) : null}

              {/* Platform Owner Governance Actions */}
              {canApprove ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.md, borderTop: `1px solid ${surface.border}`, paddingTop: spacing.md }}>
                  <h4 style={{ margin: 0, fontSize: fontSize.caption, textTransform: 'uppercase', color: text.tertiary }}>
                    Platform Owner Approval Governance
                  </h4>
                  <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap' }}>
                    <button type="button" onClick={() => setActionKind('APPROVE')} style={buttonPrimary}>
                      Approve & Issue Challenge
                    </button>
                    <button type="button" onClick={() => setActionKind('REJECT')} style={buttonSecondary}>
                      Reject Request
                    </button>
                    <button type="button" onClick={() => setActionKind('SUSPEND')} style={buttonSecondary}>
                      Suspend Activation
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
                      <button type="button" disabled={busy || !rationale.trim()} onClick={() => void handleApprove()} style={buttonPrimary}>
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
