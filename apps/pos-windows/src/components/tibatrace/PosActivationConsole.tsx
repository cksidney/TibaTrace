import { action, spacing, surface, text } from '@dawatrace/shared/design-system/index.js';
import type { PosActivationRequestDTO } from '@dawatrace/shared/dispensing/index.js';
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';

interface SetupOptions {
  branches: { id: string; code: string; name: string }[];
  registers: { id: string; branchId: string; code: string; name: string; available: boolean }[];
}
type Decision = 'approve' | 'reject' | 'revoke' | 'issue-code' | 'suspend' | 'resume' | 'release-register';
const labels: Record<Decision, string> = {
  approve: 'Approve & Issue Challenge', reject: 'Reject Request', revoke: 'Revoke Device',
  'issue-code': 'Issue renewal / recovery code', suspend: 'Suspend device', resume: 'Resume device',
  'release-register': 'Release register for replacement',
};
async function checked(response: Response) {
  const body = await response.json() as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof body['detail'] === 'string' ? body['detail'] : `Activation request refused (${response.status}).`);
  return body;
}

export function PosActivationConsole({ apiFetch, userId, userCapabilities, isPlatformOwnerContext, tenantId, deviceId,
  fingerprint = '', appVersion = '', onEnrolled, passwordChangeRequired = false,
}: {
  readonly apiFetch: typeof fetch; readonly userId: string; readonly userRole: string;
  readonly userCapabilities: readonly string[]; readonly isPlatformOwnerContext: boolean;
  readonly tenantId: string; readonly deviceId: string; readonly fingerprint?: string; readonly appVersion?: string;
  readonly onEnrolled?: () => Promise<void>; readonly passwordChangeRequired?: boolean;
}) {
  const [requests, setRequests] = useState<readonly PosActivationRequestDTO[]>([]);
  const [setup, setSetup] = useState<SetupOptions>({ branches: [], registers: [] });
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const latch = useRef(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [dialog, setDialog] = useState<'request' | Decision | null>(null);
  const [branch, setBranch] = useState('');
  const [register, setRegister] = useState('');
  const [name, setName] = useState('');
  const [reason, setReason] = useState('');
  const [rationale, setRationale] = useState('');
  const [code, setCode] = useState('');
  const [issued, setIssued] = useState<{ code: string; request: string; expiry: string } | null>(null);
  const owner = isPlatformOwnerContext && userCapabilities.includes('platform.pos_activation.approve');
  const requester = !isPlatformOwnerContext && (userCapabilities.includes('identity.manage') || userCapabilities.includes('tenant.pos_activation.request') || userCapabilities.includes('*'));
  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const endpoint = isPlatformOwnerContext
        ? `/api/v1/platform/pos-activations/requests/?tenant_id=${encodeURIComponent(tenantId)}`
        : `/api/v1/tenant/pos-activations/requests/?device_id=${encodeURIComponent(deviceId)}`;
      const response = await apiFetch(endpoint, { headers: { Accept: 'application/json' } });
      const body = await checked(response);
      setRequests((Array.isArray(body) ? body : body['results'] ?? []) as PosActivationRequestDTO[]);
      if (requester) {
        const options = await checked(await apiFetch('/api/v1/tenant/pos-activations/requests/options/'));
        setSetup(options as unknown as SetupOptions);
      }
      if (!quiet) setError('');
    } catch (cause) {
      if (!quiet) setError(cause instanceof Error ? cause.message : 'Activation service unavailable.');
    } finally { if (!quiet) setLoading(false); }
  }, [apiFetch, isPlatformOwnerContext, tenantId, deviceId, requester]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => { if (!latch.current) void refresh(true); }, 15000);
    return () => clearInterval(timer);
  }, [refresh]);
  const selected = useMemo(() => requests.find(row => row.id === selectedId) ?? requests[0], [requests, selectedId]);
  const available = setup.registers.filter(row => row.branchId === branch && row.available);
  const perform = async (operation: () => Promise<void>) => {
    if (latch.current) return;
    latch.current = true; setBusy(true); setError(''); setNotice('');
    try { await operation(); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Activation action failed.'); }
    finally { latch.current = false; setBusy(false); }
  };
  const post = async (path: string, data: object) => checked(await apiFetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(data),
  }));
  const submit = () => perform(async () => {
    if (dialog === 'request') {
      if (!branch || !available.some(row => row.code === register) || !name.trim() || reason.trim().length < 10 || fingerprint.length < 16) throw new Error('Select an available register and complete the device name and justification.');
      const result = await post('/api/v1/tenant/pos-activations/requests/', {
        tenant_id: tenantId, branch_id: branch, requested_register: register, device_id: deviceId,
        device_name: name.trim(), device_type: 'DESKTOP_WINDOWS', device_fingerprint: fingerprint,
        app_version: appVersion, business_justification: reason.trim(),
      });
      setSelectedId(String(result['id'])); setNotice('Request submitted. A different platform owner must review it.');
      setReason('');
    } else if (dialog && selected) {
      if (rationale.trim().length < 10) throw new Error('Record a rationale of at least 10 characters.');
      const result = await post(`/api/v1/platform/pos-activations/requests/${selected.id}/${dialog}/`, { rationale: rationale.trim() });
      if (typeof result['challengeCode'] === 'string') setIssued({ code: result['challengeCode'], request: selected.id, expiry: String(result['challengeExpiresAt'] ?? '') });
      setNotice(`${labels[dialog]} completed.`); setRationale('');
    }
    setDialog(null); await refresh();
  });
  const enrol = () => perform(async () => {
    if (!selected || !code.trim()) return;
    await post(`/api/v1/tenant/pos-activations/requests/${selected.id}/enrol/`, {
      challenge_code: code.trim(), device_id: deviceId, device_fingerprint: fingerprint,
    });
    setCode(''); setNotice('Enrolment saved securely. Checking activation before trading.');
    await onEnrolled?.(); await refresh();
  });
  const positive = selected?.requestingUserId !== userId;
  const decisions: Decision[] = selected?.state === 'SUBMITTED' ? ['approve','reject','revoke']
    : selected?.state === 'APPROVED' ? ['issue-code','revoke']
      : selected?.state === 'ACTIVATED' ? ['issue-code','suspend','revoke']
        : selected?.state === 'SUSPENDED' ? ['resume','revoke'] : selected?.state === 'REVOKED' ? ['release-register'] : [];
  const canEnrol = requester && selected?.deviceId === deviceId && (selected.state === 'APPROVED' || (selected.state === 'ACTIVATED' && selected.challengeAvailable));
  return <main className="pos-support-workspace" style={{ padding: spacing.lg, display: 'grid', gap: spacing.md }}>
    <header style={{ display: 'flex', gap: 16, justifyContent: 'space-between', flexWrap: 'wrap' }}>
      <div><p className="pos-eyebrow">Device enrolment</p><h1>Activate this POS</h1><p>Independent approval links this installation to one branch and physical till.</p></div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button style={secondary} disabled={busy || loading} onClick={() => void refresh()}>{loading ? 'Checking…' : 'Refresh approval status'}</button>
        {requester && <button style={primary} disabled={busy || passwordChangeRequired || requests.some(row => ['SUBMITTED','APPROVED','ACTIVATED','SUSPENDED'].includes(row.state))} onClick={() => setDialog('request')}>Submit Activation Request</button>}
      </div>
    </header>
    {passwordChangeRequired && <p role="alert">Change your temporary password in HQ, then sign out and sign in again on this till.</p>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <section style={card}><strong>This installation</strong><p style={{ overflowWrap: 'anywhere' }}>Device: {deviceId}<br />Installation fingerprint: {fingerprint || 'Unavailable'}</p><small>The fingerprint identifies this installation; it is not hardware attestation.</small></section>
    {issued && <section style={card} role="status"><strong>One-time enrolment code</strong><p>Request {issued.request} · expires {issued.expiry ? new Date(issued.expiry).toLocaleString() : 'in 15 minutes'}</p><code style={{ overflowWrap: 'anywhere' }}>{issued.code}</code><p>Give it directly to the requesting manager. A new code invalidates the previous one.</p><button style={secondary} onClick={() => setIssued(null)}>Hide code</button></section>}
    {requests.length > 1 && <label style={field}>Activation request<select style={input} value={selected?.id ?? ''} onChange={e => { setSelectedId(e.target.value); setCode(''); }}>
      {requests.map(row => <option key={row.id} value={row.id}>{row.deviceName} · {row.state}</option>)}
    </select></label>}
    {selected ? <section style={card}>
      <h2>{selected.deviceName}</h2><strong>{selected.credentialExpired && selected.state === 'ACTIVATED' ? 'EXPIRED — renewal required' : selected.state}</strong>
      <p>Register {selected.requestedRegister} · {selected.businessJustification}</p>
      {selected.activationExpiry && <p>Credential expires: {new Date(selected.activationExpiry).toLocaleString()}</p>}
      {selected.state === 'APPROVED' && !selected.challengeAvailable && <p>The code has expired or is unavailable. Ask a different platform owner to issue a recovery code.</p>}
      {selected.state === 'ACTIVATED' && !selected.challengeAvailable && !owner && <p>If this installation cannot validate its saved credential, ask the platform owner to issue a renewal / recovery code. No new request is needed.</p>}
      {canEnrol && <div style={{ display: 'grid', gap: 12, maxWidth: 600 }}><label style={field}>One-time enrolment challenge<input style={input} value={code} onChange={e => setCode(e.target.value)} autoComplete="off" /></label><button style={primary} disabled={busy || passwordChangeRequired || !code.trim()} onClick={() => void enrol()}>Complete device enrolment</button></div>}
      {owner && <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>{decisions.map(decision => <button key={decision} style={secondary} disabled={busy || (['approve','reject','issue-code','resume','release-register'].includes(decision) && !positive)} onClick={() => { setRationale(''); setDialog(decision); }}>{labels[decision]}</button>)}</div>}
      {owner && !positive && <p>A different platform owner must review requests you submitted.</p>}
    </section> : <section style={card}><h2>No activation request yet</h2><p>{requester ? 'Select an available branch and till to request independent approval.' : 'Ask an authorised tenant manager to sign in on this installation and request activation.'}</p></section>}
    <p>After activation, open the register with an opening cash count. An open business day and operator authority are still required.</p>
    {dialog && <ActivationDialog title={dialog === 'request' ? 'Request POS activation' : labels[dialog]} busy={busy} onClose={() => setDialog(null)}>
      {error && <p role="alert">{error}</p>}
      <form onSubmit={e => { e.preventDefault(); void submit(); }}><fieldset disabled={busy} style={{ border: 0, padding: 0, display: 'grid', gap: 16 }}>
        {dialog === 'request' ? <>
          <label style={field}>Branch<select required style={input} value={branch} onChange={e => { setBranch(e.target.value); setRegister(''); }}><option value="">Choose branch</option>{setup.branches.map(row => <option value={row.id} key={row.id}>{row.name} · {row.code}</option>)}</select></label>
          <label style={field}>Physical register<select required style={input} value={register} onChange={e => setRegister(e.target.value)}><option value="">Choose available till</option>{available.map(row => <option key={row.id} value={row.code}>{row.code} · {row.name}</option>)}</select></label>
          {branch && !available.length && <p>No unassigned tills are available. Create one in HQ → Finance & Cash Control → Register Physical Till, or complete the governed replacement process.</p>}
          <label style={field}>Device name<input required maxLength={160} style={input} value={name} onChange={e => setName(e.target.value)} /></label>
          <label style={field}>Business justification<textarea required minLength={10} maxLength={2000} rows={3} style={input} value={reason} onChange={e => setReason(e.target.value)} /></label>
        </> : <>
          {dialog === 'issue-code' && <p>This invalidates any previous code. The existing credential remains valid until its expiry, suspension or replacement. Enrolment on the approved installation rotates the credential and renews it for 365 days.</p>}
          {dialog === 'release-register' && <p>Close and reconcile the old till first. This releases its assignment; the replacement installation must submit a fresh request for independent approval.</p>}
          {dialog === 'suspend' && <p>Trading is blocked immediately. The register session and cash accountability remain in place.</p>}
          {dialog === 'resume' && <p>Resume this installation. An expired or missing credential still requires a renewal / recovery code.</p>}
          <label style={field}>Decision rationale<textarea required minLength={10} maxLength={2000} rows={3} style={input} value={rationale} onChange={e => setRationale(e.target.value)} /></label>
        </>}
        <div style={{ display: 'flex', gap: 12 }}><button style={secondary} type="button" onClick={() => setDialog(null)}>Cancel</button><button style={primary} type="submit">{busy ? 'Saving…' : dialog === 'request' ? 'Submit request' : `Confirm ${labels[dialog]}`}</button></div>
      </fieldset></form>
    </ActivationDialog>}
  </main>;
}

function ActivationDialog({ title, busy, onClose, children }: { title: string; busy: boolean; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('select, input, textarea, button')?.focus();
    return () => previous?.focus();
  }, []);
  return <div className="pos-compact-dialog-backdrop" style={{ position: 'fixed', inset: 0, zIndex: 100, background: '#0b122988', display: 'grid', placeItems: 'center', padding: 20 }} onClick={e => { if (e.target === e.currentTarget && !busy) onClose(); }}>
    <section className="pos-compact-dialog" ref={ref} role="dialog" aria-modal="true" aria-labelledby="activation-dialog-title" style={{ ...card, width: 'min(640px, 100%)', maxHeight: '90dvh', overflowY: 'auto', boxSizing: 'border-box' }} onKeyDown={e => {
      if (e.key === 'Escape' && !busy) { e.preventDefault(); onClose(); }
      if (e.key === 'Tab') {
        const fields = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)') ?? []);
        const next = e.shiftKey ? fields[fields.length - 1] : fields[0];
        if ((e.shiftKey && document.activeElement === fields[0]) || (!e.shiftKey && document.activeElement === fields[fields.length - 1])) { e.preventDefault(); next?.focus(); }
      }
    }}><h2 id="activation-dialog-title">{title}</h2>{children}</section>
  </div>;
}
const card: CSSProperties = { background: surface.raised, border: `1px solid ${surface.border}`, borderRadius: 16, padding: 24, color: text.primary, minWidth: 0 };
const field: CSSProperties = { display: 'grid', gap: 8, fontWeight: 600 };
const input: CSSProperties = { padding: 12, border: `1px solid ${surface.border}`, borderRadius: 8, background: surface.raised, color: text.primary, font: 'inherit', width: '100%', boxSizing: 'border-box' };
const primary: CSSProperties = { padding: '12px 18px', border: 0, borderRadius: 8, background: action.primary, color: text.inverse, fontWeight: 700, cursor: 'pointer' };
const secondary: CSSProperties = { ...primary, background: surface.raised, color: text.primary, border: `1px solid ${surface.border}` };
