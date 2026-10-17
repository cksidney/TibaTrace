import { useCallback, useEffect, useMemo, useState } from 'react';

import type { HQOverview } from './api.js';
import { Icon } from './icons.js';

export interface PosActivationSummary {
  readonly id: string;
  readonly tenantId: string;
  readonly branchId: string;
  readonly register: string;
  readonly requestedRegister?: string;
  readonly deviceName: string;
  readonly deviceType: string;
  readonly deviceFingerprint: string;
  readonly requester: string;
  readonly requesterEmailSnapshot?: string | undefined;
  readonly requesterRole?: string | undefined;
  readonly businessJustification?: string | undefined;
  readonly justification: string;
  readonly state: 'SUBMITTED' | 'APPROVED' | 'ACTIVATED' | 'REJECTED' | 'REVOKED' | string;
  readonly appVersion?: string | undefined;
  readonly submittedAt?: string | undefined;
  readonly approvalRationale?: string | undefined;
  readonly activationExpiry?: string | null | undefined;
  readonly challengeCode?: string | undefined;
  readonly challengeExpiresAt?: string | undefined;
}

export interface IssuedChallenge {
  readonly code: string;
  readonly expiresAt?: string | undefined;
  readonly deviceName: string;
  readonly register: string;
  readonly requestId: string;
}

interface PosActivationWorkspaceProps {
  readonly csrfToken: string;
  readonly isPlatformOwner?: boolean;
  readonly tenantId?: string | null;
  readonly overview?: HQOverview;
}

export function PosActivationWorkspace({
  csrfToken,
  isPlatformOwner = false,
  tenantId,
  overview,
}: PosActivationWorkspaceProps) {
  const [filter, setFilter] = useState<'ALL' | 'SUBMITTED' | 'APPROVED' | 'ACTIVATED' | 'REVOKED' | 'REJECTED'>('ALL');
  const [search, setSearch] = useState('');
  const [selectedTenant, setSelectedTenant] = useState<string>(tenantId || 'ALL');
  const [activations, setActivations] = useState<readonly PosActivationSummary[]>([]);
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);
  const [serviceState, setServiceState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [actionBusy, setActionBusy] = useState<'approve' | 'reject' | 'revoke' | ''>('');
  const [approvalRationale, setApprovalRationale] = useState('');
  const [revokeRationale, setRevokeRationale] = useState('');
  const [showRevokeDialog, setShowRevokeDialog] = useState(false);
  const [issuedChallenge, setIssuedChallenge] = useState<IssuedChallenge | null>(null);
  const [copied, setCopied] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const loadActivationRequests = useCallback(async (signal?: AbortSignal) => {
    setServiceState('loading');
    setError('');
    try {
      let endpoint = '';
      if (isPlatformOwner) {
        endpoint = selectedTenant && selectedTenant !== 'ALL'
          ? `/api/v1/platform/pos-activations/requests/?tenant_id=${encodeURIComponent(selectedTenant)}`
          : '/api/v1/platform/pos-activations/requests/';
      } else {
        const tenant = tenantId || selectedTenant;
        endpoint = tenant && tenant !== 'ALL'
          ? `/api/v1/tenant/pos-activations/requests/?tenant_id=${encodeURIComponent(tenant)}`
          : '/api/v1/tenant/pos-activations/requests/';
      }

      const request: RequestInit = {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      };
      if (signal) request.signal = signal;

      const response = await fetch(endpoint, request);
      if (!response.ok) {
        throw new Error(`Activation service returned HTTP ${response.status}.`);
      }
      const data = (await response.json()) as PosActivationSummary[] | { results?: PosActivationSummary[] };
      const items = Array.isArray(data) ? data : (data.results ?? []);
      setActivations(items);
      setServiceState('ready');
    } catch {
      if (signal?.aborted) return;
      setActivations([]);
      setServiceState('unavailable');
    }
  }, [isPlatformOwner, selectedTenant, tenantId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadActivationRequests(controller.signal);
    return () => controller.abort();
  }, [loadActivationRequests]);

  const filtered = useMemo(() => {
    return activations.filter((a) => {
      const matchFilter = filter === 'ALL' || a.state === filter;
      const matchSearch =
        !search.trim() ||
        [a.id, a.deviceName, a.branchId, a.register, a.requestedRegister, a.requester, a.justification, a.businessJustification]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(search.trim().toLowerCase());
      return matchFilter && matchSearch;
    });
  }, [activations, filter, search]);

  const activeItem = useMemo(
    () => activations.find((a) => a.id === selectedRequestId) ?? filtered[0] ?? null,
    [activations, filtered, selectedRequestId],
  );

  const pendingCount = useMemo(() => activations.filter((item) => item.state === 'SUBMITTED').length, [activations]);
  const approvedCount = useMemo(() => activations.filter((item) => item.state === 'APPROVED').length, [activations]);
  const activatedCount = useMemo(() => activations.filter((item) => item.state === 'ACTIVATED').length, [activations]);
  const revokedCount = useMemo(() => activations.filter((item) => item.state === 'REVOKED' || item.state === 'REJECTED').length, [activations]);

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch {
      setError('Unable to copy to clipboard automatically. Please copy the code manually.');
    }
  };

  const handleDecision = async (decision: 'approve' | 'reject') => {
    if (!activeItem) return;
    const rationale = approvalRationale.trim();
    if (rationale.length < 10) {
      setError('A review rationale of at least 10 characters is required for audited governance.');
      return;
    }

    setActionBusy(decision);
    setError('');
    setNotice('');
    try {
      const response = await fetch(`/api/v1/platform/pos-activations/requests/${encodeURIComponent(activeItem.id)}/${decision}/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          rationale,
          approval_rationale: rationale,
        }),
      });

      if (!response.ok) {
        const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(errorData.detail || `Activation service returned HTTP ${response.status}.`);
      }

      const payload = (await response.json().catch(() => ({}))) as {
        challengeCode?: string;
        challenge_code?: string;
        challengeExpiresAt?: string;
      };

      if (decision === 'approve') {
        const challenge = payload.challengeCode ?? payload.challenge_code;
        if (!challenge) {
          throw new Error('Activation service did not return an enrolment challenge.');
        }
        setIssuedChallenge({
          code: challenge,
          expiresAt: payload.challengeExpiresAt,
          deviceName: activeItem.deviceName,
          register: activeItem.register || activeItem.requestedRegister || 'Default Till',
          requestId: activeItem.id,
        });
        setNotice(`Terminal request approved! Enrolment challenge issued for ${activeItem.deviceName}.`);
      } else {
        setNotice(`Request ${activeItem.id} rejected with audit rationale.`);
      }

      setApprovalRationale('');
      await loadActivationRequests();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Action failed closed.';
      setError(`${decision === 'approve' ? 'Approval' : 'Rejection'} failed: ${msg}`);
    } finally {
      setActionBusy('');
    }
  };

  const handleRevoke = async () => {
    if (!activeItem) return;
    const rationale = revokeRationale.trim();
    if (rationale.length < 10) {
      setError('A revocation rationale of at least 10 characters is required for audit logs.');
      return;
    }

    setActionBusy('revoke');
    setError('');
    setNotice('');
    try {
      const response = await fetch(`/api/v1/platform/pos-activations/requests/${encodeURIComponent(activeItem.id)}/revoke/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({ rationale }),
      });

      if (!response.ok) {
        const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(errorData.detail || `Revocation failed with HTTP ${response.status}.`);
      }

      setNotice(`Terminal ${activeItem.deviceName} credentials have been revoked immediately.`);
      setShowRevokeDialog(false);
      setRevokeRationale('');
      await loadActivationRequests();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Revocation failed.';
      setError(`Revocation failed: ${msg}`);
    } finally {
      setActionBusy('');
    }
  };

  return (
    <div className="pos-activation-workspace">
      {/* Platform & Governance Banner */}
      <section className="panel pos-activation-header">
        <div className="pos-activation-header-content">
          <div className="pos-activation-badge-row">
            <span className="status-badge status-active">
              <Icon name="shield" /> {isPlatformOwner ? 'Platform Owner Authority' : 'Tenant Device Desk'}
            </span>
            {pendingCount > 0 ? (
              <span className="status-badge status-warning pulse-badge">
                <Icon name="alert" /> {pendingCount} Pending Enrolment{pendingCount === 1 ? '' : 's'}
              </span>
            ) : null}
          </div>
          <h2>POS Terminal Activations & Device Registry</h2>
          <p>
            Governed device enrolment desk. Review incoming terminal activation requests, generate cryptographically signed 15-minute challenge codes, bind POS Windows devices to store registers, and revoke compromised device credentials.
          </p>
        </div>
        <div className="pos-activation-header-actions">
          <button
            className="secondary-button"
            disabled={serviceState === 'loading'}
            onClick={() => void loadActivationRequests()}
            type="button"
          >
            <Icon name="refresh" /> Refresh Registry
          </button>
        </div>
      </section>

      {/* Prominent Issued Challenge Card */}
      {issuedChallenge ? (
        <section className="panel pos-challenge-card" role="region" aria-label="Active Enrolment Challenge Code">
          <header className="pos-challenge-card-header">
            <div>
              <span className="eyebrow"><Icon name="shield" /> Single-Use Security Challenge</span>
              <h3>Enrolment Challenge Code for {issuedChallenge.deviceName}</h3>
              <p className="muted-cell">
                Register: <strong>{issuedChallenge.register}</strong> · Request ID: <code>{issuedChallenge.requestId}</code>
              </p>
            </div>
            <div className="pos-challenge-expiry-badge">
              <span className="status-badge status-warning">
                <Icon name="activity" /> Valid for 15 Minutes
              </span>
            </div>
          </header>

          <div className="pos-challenge-code-container">
            <div className="pos-challenge-code-box">
              <span className="pos-challenge-code-label">One-Time Activation Code</span>
              <code className="pos-challenge-code-display">{issuedChallenge.code}</code>
            </div>
            <button
              className="primary-button pos-challenge-copy-btn"
              onClick={() => void copyToClipboard(issuedChallenge.code)}
              type="button"
            >
              {copied ? (
                <>
                  <Icon name="check" /> Copied to Clipboard!
                </>
              ) : (
                <>
                  <Icon name="docs" /> Copy Challenge Code
                </>
              )}
            </button>
          </div>

          <div className="pos-challenge-instructions">
            <strong><Icon name="store" /> Next Steps for Cashier / Field Technician at the POS Till:</strong>
            <ol>
              <li>Open <strong>TibaTrace POS Windows</strong> desktop application on the physical till terminal.</li>
              <li>When prompted by the <strong>Device Activation</strong> screen, confirm device details.</li>
              <li>Enter or paste this <strong>Challenge Code</strong> into the activation dialog.</li>
              <li>Submit to complete enrolment. The terminal will automatically receive an encrypted 365-day device token bound to register <code>{issuedChallenge.register}</code>.</li>
            </ol>
          </div>

          <footer className="pos-challenge-footer">
            <button
              className="ghost-button"
              onClick={() => setIssuedChallenge(null)}
              type="button"
            >
              Dismiss Challenge Banner
            </button>
          </footer>
        </section>
      ) : null}

      {/* Metrics Row */}
      <section aria-label="Terminal Activation Totals" className="activation-metrics">
        <div className={pendingCount > 0 ? 'activation-metric-alert' : ''}>
          <span>Pending Review</span>
          <strong style={{ color: pendingCount > 0 ? 'var(--gold-400)' : 'inherit' }}>
            {pendingCount}
          </strong>
        </div>
        <div>
          <span>Enrolment Issued</span>
          <strong>{approvedCount}</strong>
        </div>
        <div>
          <span>Active Terminals</span>
          <strong style={{ color: 'var(--teal-500)' }}>{activatedCount}</strong>
        </div>
        <div>
          <span>Revoked / Rejected</span>
          <strong>{revokedCount}</strong>
        </div>
      </section>

      {/* Filter and Search Bar */}
      <div className="access-users-toolbar">
        <form className="access-users-search" onSubmit={(e) => e.preventDefault()}>
          <label>
            <span>Search terminals & requests</span>
            <input
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by device name, ID, branch, register, or requester…"
              value={search}
            />
          </label>
        </form>

        {isPlatformOwner && overview?.is_platform_overview ? (
          <label className="access-tenant-select">
            <span>Filter Tenant Workspace</span>
            <select onChange={(e) => setSelectedTenant(e.target.value)} value={selectedTenant}>
              <option value="ALL">All Tenants (Global Platform View)</option>
              {overview.network_items?.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          </label>
        ) : null}

        <label>
          <span>Status Filter</span>
          <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            <option value="ALL">All Statuses ({activations.length})</option>
            <option value="SUBMITTED">Pending Review ({pendingCount})</option>
            <option value="APPROVED">Enrolment Issued ({approvedCount})</option>
            <option value="ACTIVATED">Active Terminals ({activatedCount})</option>
            <option value="REVOKED">Revoked</option>
            <option value="REJECTED">Rejected</option>
          </select>
        </label>
      </div>

      {notice ? <p className="inline-success" role="status"><Icon name="check" /> {notice}</p> : null}
      {error ? <p className="inline-alert" role="alert"><Icon name="alert" /> {error}</p> : null}

      {serviceState === 'loading' ? (
        <div className="activation-service-state" role="status">
          <span className="activation-service-icon"><Icon name="refresh" /></span>
          <div>
            <strong>Connecting to Authoritative Activation Registry</strong>
            <p>Fetching POS terminal enrolment records and cryptographic keys…</p>
          </div>
        </div>
      ) : serviceState === 'unavailable' ? (
        <div className="activation-service-unavailable" role="status">
          <div className="activation-service-state">
            <span className="activation-service-icon"><Icon name="shield" /></span>
            <div>
              <span className="status-badge status-warning"><i /> Fail Closed</span>
              <h3>Activation Service Unreachable</h3>
              <p>Device requests and Platform Owner decisions are disabled until authoritative service connectivity is restored.</p>
            </div>
            <button className="secondary-button" onClick={() => void loadActivationRequests()} type="button">
              Retry Connection
            </button>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="activation-empty-state">
          <span className="activation-service-icon"><Icon name="store" /></span>
          <div>
            <strong>No Terminal Activations Found</strong>
            <p>
              {search || filter !== 'ALL'
                ? 'No activation records match the current filters.'
                : 'New POS terminal activation requests submitted by store registers will appear here for explicit review.'}
            </p>
          </div>
        </div>
      ) : (
        <div className="activation-review-layout">
          {/* Main Table */}
          <div className="table-scroll">
            <table className="access-users-table">
              <thead>
                <tr>
                  <th scope="col">Terminal / Device</th>
                  <th scope="col">Register & Branch</th>
                  <th scope="col">Requester</th>
                  <th scope="col">Status</th>
                  <th scope="col">Submitted</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => {
                  const isSelected = activeItem?.id === item.id;
                  const isPending = item.state === 'SUBMITTED';
                  const isApproved = item.state === 'APPROVED';
                  const isActivated = item.state === 'ACTIVATED';
                  return (
                    <tr key={item.id} className={isSelected ? 'is-selected' : ''}>
                      <td>
                        <strong>{item.deviceName}</strong>
                        <small className="muted-cell" style={{ display: 'block' }}>
                          ID: <code>{item.id.slice(0, 8)}…</code> · {item.deviceType}
                        </small>
                      </td>
                      <td>
                        <strong>{item.register || item.requestedRegister}</strong>
                        <small className="muted-cell" style={{ display: 'block' }}>
                          Branch: {item.branchId.slice(0, 8)}…
                        </small>
                      </td>
                      <td>
                        <span>{item.requester}</span>
                        {item.requesterEmailSnapshot ? (
                          <small className="muted-cell" style={{ display: 'block' }}>
                            {item.requesterEmailSnapshot}
                          </small>
                        ) : null}
                      </td>
                      <td>
                        <span
                          className={`status-badge status-${
                            isActivated ? 'active' : isPending ? 'warning' : isApproved ? 'active' : 'suspended'
                          }`}
                        >
                          <i /> {item.state}
                        </span>
                      </td>
                      <td>
                        <span className="muted-cell">
                          {item.submittedAt ? new Date(item.submittedAt).toLocaleDateString() : '—'}
                        </span>
                      </td>
                      <td>
                        <button
                          className={isPending ? 'primary-button' : 'ghost-button'}
                          onClick={() => setSelectedRequestId(item.id)}
                          type="button"
                        >
                          {isPending ? 'Review & Issue' : 'View Details'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Active Item Review Drawer / Card */}
          {activeItem ? (
            <aside className="activation-review-card">
              <div className="activation-review-heading">
                <div>
                  <span className="eyebrow">Terminal Record</span>
                  <h3>{activeItem.deviceName}</h3>
                </div>
                <span
                  className={`status-badge status-${
                    activeItem.state === 'ACTIVATED'
                      ? 'active'
                      : activeItem.state === 'SUBMITTED'
                      ? 'warning'
                      : activeItem.state === 'APPROVED'
                      ? 'active'
                      : 'suspended'
                  }`}
                >
                  <i /> {activeItem.state}
                </span>
              </div>

              <small className="muted-cell">
                Request UUID: <code>{activeItem.id}</code> · Tenant: <code>{activeItem.tenantId}</code>
              </small>

              <dl className="activation-request-details">
                <div>
                  <dt>Target Till</dt>
                  <dd>
                    <strong>{activeItem.register || activeItem.requestedRegister}</strong>
                  </dd>
                </div>
                <div>
                  <dt>Branch UUID</dt>
                  <dd><code>{activeItem.branchId}</code></dd>
                </div>
                <div>
                  <dt>Device Fingerprint</dt>
                  <dd><code>{activeItem.deviceFingerprint}</code></dd>
                </div>
                <div>
                  <dt>Requester</dt>
                  <dd>
                    {activeItem.requester}
                    {activeItem.requesterEmailSnapshot ? ` (${activeItem.requesterEmailSnapshot})` : ''}
                  </dd>
                </div>
                <div>
                  <dt>Business Justification</dt>
                  <dd>{activeItem.justification || activeItem.businessJustification || '—'}</dd>
                </div>
                {activeItem.approvalRationale ? (
                  <div>
                    <dt>Approval Rationale</dt>
                    <dd>{activeItem.approvalRationale}</dd>
                  </div>
                ) : null}
                {activeItem.activationExpiry ? (
                  <div>
                    <dt>Credential Expiry</dt>
                    <dd>{new Date(activeItem.activationExpiry).toLocaleString()}</dd>
                  </div>
                ) : null}
              </dl>

              {/* Pending Action Panel */}
              {activeItem.state === 'SUBMITTED' && isPlatformOwner ? (
                <div className="activation-decision-panel">
                  <strong>Platform Owner Approval & Challenge Issuance</strong>
                  <label>
                    <span>Audit Decision Rationale (min 10 characters)</span>
                    <textarea
                      onChange={(e) => setApprovalRationale(e.target.value)}
                      placeholder="e.g. Authorized hardware terminal for Pharmacy Main Branch Till 1."
                      rows={3}
                      value={approvalRationale}
                    />
                  </label>

                  <div className="activation-decision-actions">
                    <button
                      className="primary-button"
                      disabled={Boolean(actionBusy) || approvalRationale.trim().length < 10}
                      onClick={() => void handleDecision('approve')}
                      type="button"
                    >
                      {actionBusy === 'approve' ? 'Issuing Code…' : 'Approve & Issue Code'}
                    </button>
                    <button
                      className="secondary-button"
                      disabled={Boolean(actionBusy) || approvalRationale.trim().length < 10}
                      onClick={() => void handleDecision('reject')}
                      type="button"
                    >
                      {actionBusy === 'reject' ? 'Rejecting…' : 'Reject Request'}
                    </button>
                  </div>
                  <small className="muted-cell">
                    Approving generates a single-use 15-minute challenge code that the cashier must enter on the POS Windows till.
                  </small>
                </div>
              ) : null}

              {/* Revoke Action for Active / Approved Terminals */}
              {(activeItem.state === 'ACTIVATED' || activeItem.state === 'APPROVED') && isPlatformOwner ? (
                <div className="activation-revoke-panel">
                  {!showRevokeDialog ? (
                    <button
                      className="secondary-button"
                      onClick={() => setShowRevokeDialog(true)}
                      style={{ color: 'var(--rose-400)', borderColor: 'var(--rose-400)' }}
                      type="button"
                    >
                      <Icon name="shield" /> Revoke Terminal Credential
                    </button>
                  ) : (
                    <div className="activation-revoke-form">
                      <strong>Revoke Device Access</strong>
                      <p className="muted-cell" style={{ margin: '4px 0 8px' }}>
                        Revoking will immediately invalidate the terminal's cryptographic certificate. The POS till will be locked out from selling.
                      </p>
                      <label>
                        <span>Revocation Rationale (min 10 characters)</span>
                        <textarea
                          onChange={(e) => setRevokeRationale(e.target.value)}
                          placeholder="e.g. Terminal hardware decommissioned or security token compromised."
                          rows={2}
                          value={revokeRationale}
                        />
                      </label>
                      <div className="activation-decision-actions" style={{ marginTop: '8px' }}>
                        <button
                          className="secondary-button"
                          disabled={Boolean(actionBusy) || revokeRationale.trim().length < 10}
                          onClick={() => void handleRevoke()}
                          style={{ background: 'var(--rose-400)', color: '#fff' }}
                          type="button"
                        >
                          {actionBusy === 'revoke' ? 'Revoking…' : 'Confirm Immediate Revoke'}
                        </button>
                        <button
                          className="ghost-button"
                          onClick={() => {
                            setShowRevokeDialog(false);
                            setRevokeRationale('');
                          }}
                          type="button"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : null}

              {activeItem.state !== 'SUBMITTED' && activeItem.state !== 'ACTIVATED' && activeItem.state !== 'APPROVED' ? (
                <p className="activation-decision-complete">
                  This terminal request is in state <strong>{activeItem.state}</strong>. Terminal credentials cannot be modified without a new governed submission.
                </p>
              ) : null}
            </aside>
          ) : null}
        </div>
      )}
    </div>
  );
}
