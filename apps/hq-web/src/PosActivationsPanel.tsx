import { useCallback, useEffect, useRef, useState } from 'react';
import { IntakeModal } from './IntakeModal.js';

interface Activation {
  id: string; tenantId: string; branchId: string; register: string; deviceName: string;
  deviceFingerprint: string; requester: string; requestingUserId: string; justification: string; state: string;
  challengeExpiresAt?: string | null; activationExpiry?: string | null; credentialExpired?: boolean;
}
type Decision = 'approve' | 'reject' | 'issue-code' | 'suspend' | 'resume' | 'revoke' | 'release-register';
const labels: Record<Decision, string> = { approve: 'Approve & issue code', reject: 'Reject request', 'issue-code': 'Issue renewal / recovery code', suspend: 'Suspend device', resume: 'Resume device', revoke: 'Revoke device', 'release-register': 'Release register for replacement' };

export function PosActivationsPanel({ tenantId, csrfToken, isPlatformOwner, currentUserName }: { tenantId: string; csrfToken: string; isPlatformOwner: boolean; currentUserName?: string }) {
  const [rows, setRows] = useState<Activation[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const latch = useRef(false);
  const [action, setAction] = useState<Decision | null>(null);
  const [rationale, setRationale] = useState('');
  const [challenge, setChallenge] = useState<{ code: string; requestId: string; expires: string } | null>(null);
  const [search, setSearch] = useState('');
  const headers = useCallback(() => ({ Accept: 'application/json', 'X-Tenant-ID': tenantId }), [tenantId]);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const prefix = isPlatformOwner ? 'platform' : 'tenant';
      const response = await fetch(`/api/v1/${prefix}/pos-activations/requests/?tenant_id=${encodeURIComponent(tenantId)}`, { credentials: 'same-origin', headers: headers(), ...(signal ? { signal } : {}) });
      const body = await response.json() as Activation[] | { detail?: string };
      if (!response.ok) throw new Error(!Array.isArray(body) && body.detail ? body.detail : 'Activation requests could not be loaded.');
      if (signal?.aborted) return;
      setRows(Array.isArray(body) ? body : []); setError('');
    } catch (cause) { if (!signal?.aborted) setError(cause instanceof Error ? cause.message : 'Activation service unavailable.'); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [headers, isPlatformOwner, tenantId]);
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = setInterval(() => { if (!latch.current) void refresh(controller.signal); }, 30000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [refresh]);
  const filtered = rows.filter(row => [row.deviceName, row.register, row.state, row.requester].join(' ').toLowerCase().includes(search.toLowerCase()));
  const active = filtered.find(row => row.id === selected) ?? filtered[0];
  const independentReview = active?.requester !== currentUserName;
  const decisions: Decision[] = active?.state === 'SUBMITTED' ? ['approve','reject','revoke']
    : active?.state === 'APPROVED' ? ['issue-code','revoke'] : active?.state === 'ACTIVATED' ? ['issue-code','suspend','revoke']
      : active?.state === 'SUSPENDED' ? ['resume','revoke'] : active?.state === 'REVOKED' ? ['release-register'] : [];
  const submit = async () => {
    if (!action || !active || latch.current || rationale.trim().length < 10) return;
    latch.current = true; setBusy(true); setError(''); setNotice(''); setChallenge(null);
    try {
      const response = await fetch(`/api/v1/platform/pos-activations/requests/${active.id}/${action}/`, {
        method: 'POST', credentials: 'same-origin', headers: { ...headers(), 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }, body: JSON.stringify({ rationale: rationale.trim() }),
      });
      const result = await response.json() as { detail?: string; challengeCode?: string; challengeExpiresAt?: string };
      if (!response.ok) throw new Error(result.detail ?? `Activation action refused (${response.status}).`);
      if (result.challengeCode) setChallenge({ code: result.challengeCode, requestId: active.id, expires: result.challengeExpiresAt ?? '' });
      setNotice(`${labels[action]} completed.`); setAction(null); setRationale(''); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Activation action failed.'); }
    finally { latch.current = false; setBusy(false); }
  };
  return <div className="access-activations-container">
    <p>Tenant managers request enrolment from the actual installation. A different platform owner reviews the request. Approval alone does not activate the till.</p>
    <div className="access-users-toolbar"><label>Search activations<input value={search} onChange={e => setSearch(e.target.value)} placeholder="Device, register or status" /></label><button className="secondary-button" disabled={busy} onClick={() => void refresh()}>Refresh approval status</button></div>
    {loading && <p role="status">Loading activation requests…</p>}{error && <p className="inline-alert" role="alert">{error}</p>}{notice && <p className="inline-success" role="status">{notice}</p>}
    {challenge && <section className="activation-challenge" role="status"><strong>One-time enrolment code</strong><p>Request {challenge.requestId} · expires {challenge.expires ? new Date(challenge.expires).toLocaleString() : 'in 15 minutes'}</p><code>{challenge.code}</code><p>Give it directly to the requesting manager. A new code invalidates the previous one.</p><button className="secondary-button" onClick={() => setChallenge(null)}>Hide code</button></section>}
    {!loading && !filtered.length && <p>No activation requests match this workspace.</p>}
    {active && <div className="activation-review-layout"><div className="activation-request-list">{filtered.map(row => <button className="secondary-button" key={row.id} disabled={busy} onClick={() => { setSelected(row.id); setChallenge(null); }}><strong>{row.deviceName}</strong> · {row.register} · {row.credentialExpired && row.state === 'ACTIVATED' ? 'EXPIRED' : row.state}</button>)}</div>
      <section className="activation-review-card"><h3>{active.deviceName}</h3><strong>{active.state}</strong><dl className="activation-request-details"><div><dt>Register</dt><dd>{active.register}</dd></div><div><dt>Branch</dt><dd>{active.branchId}</dd></div><div><dt>Requester</dt><dd>{active.requester}</dd></div><div><dt>Reason</dt><dd>{active.justification}</dd></div><div><dt>Credential expiry</dt><dd>{active.activationExpiry ? new Date(active.activationExpiry).toLocaleString() : 'Not enrolled'}</dd></div></dl>
        {isPlatformOwner ? <><div className="activation-decision-actions">{decisions.map(decision => <button key={decision} className="secondary-button" disabled={busy || (['approve','reject','issue-code','resume','release-register'].includes(decision) && !independentReview)} onClick={() => { setAction(decision); setRationale(''); setError(''); }}>{labels[decision]}</button>)}</div>{!independentReview && <p>A different platform owner must review requests you submitted.</p>}</> : <p>Complete enrolment on the approved POS using the platform owner's single-use code.</p>}
      </section></div>}
    {action && active && <IntakeModal title={labels[action]} busy={busy} onClose={() => setAction(null)}>
      {error && <p role="alert" className="inline-alert">{error}</p>}
      <p>{active.deviceName} · {active.register}</p>
      {action === 'issue-code' && <p>This replaces the previous code. The current credential stays valid until its expiry, suspension or replacement. Enrolment on the approved installation rotates the credential and renews it for 365 days.</p>}
      {action === 'release-register' && <p>Requires a revoked activation, a closed register and a final Z report for its previous session. The replacement installation must submit a fresh activation request.</p>}
      {action === 'suspend' && <p>Trading is blocked immediately. The open register session and cash accountability remain in place.</p>}
      {action === 'resume' && <p>Resumption preserves the credential expiry. An expired or missing credential still needs a renewal / recovery code.</p>}
      <form onSubmit={e => { e.preventDefault(); void submit(); }}><fieldset disabled={busy} style={{ border: 0, padding: 0 }}><label>Decision rationale<textarea required minLength={10} maxLength={2000} rows={4} value={rationale} onChange={e => setRationale(e.target.value)} /></label><div className="activation-decision-actions"><button className="secondary-button" type="button" onClick={() => setAction(null)}>Cancel</button><button className="primary-button" type="submit">{busy ? 'Saving…' : 'Confirm decision'}</button></div></fieldset></form>
    </IntakeModal>}
  </div>;
}
